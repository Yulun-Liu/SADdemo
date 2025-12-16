import json
import sys
import re
import pdfplumber
import os
import tempfile
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from typing import Tuple # 匯入 Tuple 型別
from dotenv import load_dotenv

#關閉flask 語法 deactivate
# === 新增：Groq 官方套件 ===
from groq import Groq

load_dotenv()

# === 初始化 Groq 客戶端 ===
# 它會自動去讀取環境變數中的 GROQ_API_KEY，所以不用手動填
client = Groq()


# === 匯入剛剛寫好的資料庫模組 ===
from save_to_db import save_student_data,get_student_data_from_db, check_user_exists

# ======================================================================
# 
#                           PART 1: PDF 解析
# 
# ======================================================================

# (這是 message_idx: 75 的效能優化版 Regex)
COURSE_PATTERN = re.compile(
    r"^\s*"  # 匹配行首的任何空白
    r"(?P<系所>本系|外系|--)\s+"
    r"(?P<課號>[A-Z0-9.]+)\s+"
    r"(?:" 
    r"(?P<冊_full>\d+)\s+(?P<學年_full>\d+)\s+(?P<期_full>\d+)"
    r"|" 
    r"(?P<期_only>\d+)"
    r")\s+" 
    r"(?P<課名>.+?)\s+"
    
    # (已優化排序，最長的放前面)
    r"(?P<選別>系必修|院必修|共同必修|共必|通識|系必|選)\s+"
    
    r"(?P<得分>通過|未過)\s+"
    r"(?P<學分>\d)\s+"
    r"(?P<累計>\d+)\s+"
    r"(?P<分數>#|\*|\d+|Pass)\s*"
    r"(?P<說明>.*)?$"
)

# (新) 抓取學生資訊的 Regex
YEAR_PATTERN = re.compile(r"修業年度:\s*(\d+)")
STUDENT_PATTERN = re.compile(r"(\d{7,})\s+([\u4e00-\u9fa5]+)\s+([\u4e00-\u9fa5\s]+)")

def parse_pdf_with_regex(file_path: str) -> Tuple[list, dict]: 
    """
    開啟 PDF，逐行讀取文字，解析「學生資訊」和「課程列表」。
    
    Returns:
        (all_courses, student_info)
    """
    
    print(f"--- (1/3)  正在使用 Regex (規則配對) 讀取: {file_path} ---")
    
    all_courses = []
    student_info = {
        "year": None,
        "id": None,
        "name": None,
        "department": None
    }
    
    # --- ↓↓↓ (Bug 修正) 將 'found_student_info' 拆分 ---
    found_year = False
    found_student = False
    # --- ↑↑↑ 修正結束 ↑↑↑ ---

    try:
        with pdfplumber.open(file_path) as pdf:
            print(f"檔案總頁數: {len(pdf.pages)}")
            
            for i, page in enumerate(pdf.pages):
                
                # (效能修正) 使用 layout=True 強制 pdfplumber 進行排版
                text = page.extract_text(layout=True) 
                
                if not text:
                    continue
                
                for line in text.split('\n'):
                    line_stripped = line.strip()
                    
                    # (新) 嘗試匹配學生資訊 (只在第一頁且尚未找到時)
                    if i == 0:
                        # --- ↓↓↓ (Bug 修正) 獨立判斷 ---
                        if not found_year:
                            year_match = YEAR_PATTERN.search(line_stripped)
                            if year_match:
                                student_info["year"] = year_match.group(1)
                                found_year = True # 標記已找到
                                
                        if not found_student:
                            student_match = STUDENT_PATTERN.search(line_stripped)
                            if student_match:
                                student_info["id"] = student_match.group(1)
                                student_info["name"] = student_match.group(2)
                                student_info["department"] = student_match.group(3).strip()
                                found_student = True # 標記已找到
                        # --- ↑↑↑ 修正結束 ↑↑↑ ---
                    
                    # 嘗試匹配課程
                    course_match = COURSE_PATTERN.match(line_stripped)
                    if course_match:
                        course_raw = course_match.groupdict()
                        course = {} 
                        
                        course['系所'] = course_raw['系所']
                        course['課號'] = course_raw['課號']
                        
                        if course_raw['期_full']:
                            course['冊'] = course_raw['冊_full']
                            course['學年'] = course_raw['學年_full']
                            course['期'] = course_raw['期_full']
                        else:
                            course['冊'] = None
                            course['學年'] = None
                            course['期'] = course_raw['期_only']
                        
                        course['課名'] = course_raw['課名']
                        course['選別'] = course_raw['選別']
                        course['得分'] = course_raw['得分']
                        course['學分'] = course_raw['學分']
                        course['累計'] = course_raw['累計']
                        course['分數'] = course_raw['分數']
                        course['說明'] = course_raw['說明']

                        for key, value in course.items():
                            if value == "" or value is None:
                                course[key] = None
                        
                        all_courses.append(course)

        if not all_courses:
            print("[警告] 成功開啟 PDF，但 Regex 未能匹配到任何課程資料。")
            return [], student_info
            
        print(f"Regex 配對成功，共擷取 {len(all_courses)} 筆課程資料。")
        print(f"學生資訊: {student_info}")
        
        return all_courses, student_info
        
    except FileNotFoundError:
        print(f"[錯誤] 找不到檔案: {file_path}")
        return [], {}
    except Exception as e:
        print(f"[錯誤] 讀取或解析 PDF 時發生意外: {e}")
        return [], {}

# ======================================================================
# 
#                           PART 2: 畢業審查 (已整合重修邏輯)
# 
# ======================================================================

def calculate_graduation_audit(all_courses: list) -> Tuple[dict, dict]:
    """
    讀取課程列表 (list)，計算學分 (已處理重修邏輯)，
    並「回傳」審查結果字典 (audit_categories) 和總計字典 (totals)。
    """
    
    print(f"--- (2/3) 正在讀取 {len(all_courses)} 筆課程資料進行審查 ---")
    
    # --- 1. 建立一個更詳細的資料結構 ---
    audit_categories = {
        "必修":     {"goal": 70, "earned_sum": 0, "earned_courses": [], "failed_courses": []},
        "院必修":   {"goal": 4,  "earned_sum": 0, "earned_courses": [], "failed_courses": []},
        "選修":     {"goal": 27, "earned_sum": 0, "earned_courses": [], "failed_courses": []},
        "通識": {
            "goal": 12, 
            "earned_sum": 0, 
            "earned_courses": [],
            "failed_courses": [], 
            "core_required_prefixes": {"LS", "LE", "ID", "GN", "GS"},
            "core_passed_prefixes": set(),
            "core_missing_prefixes": [], 
            "core_passed_count": 0,
            "is_core_complete": False 
        },
        "共同必修": {"goal": 15, "earned_sum": 0, "earned_courses": [], "failed_courses": []},
        "其他":     {"goal": 0,  "earned_sum": 0, "earned_courses": [], "failed_courses": []},
    }
    # --- 1.1: 建立共同必修四大規則追蹤 ---
    common_req_status = {
        'English': {'name': '英語', 'goal': 10, 'earned': 0},
        'Chinese': {'name': '國文', 'goal': 4, 'earned': 0},
        'Service': {'name': '服務學習', 'goal': 1, 'earned': 0},
    }
    # --- 1.2: 初始化總學分變數 ---

    total_required_credits = 128 # 畢業總學分 (如圖所示)
    total_earned_credits = 0
    # --- 1.3: 建立一個集合，追蹤所有「有通過」的課號 ---
    # 追蹤變數
    passed_course_ids_audit = set() # 這次審查中「已經算過學分」的課號
    passed_course_ids_global = set() # 所有「有通過」紀錄的課號 (用於過濾未過)
    
    # 預先掃描：建立全域通過名單
    for course in all_courses:
        if course.get("得分") == "通過":
            cid = course.get("課號")
            if cid: passed_course_ids_global.add(cid)
    print(f"--- (2/3 - Pre-Scan) 建立全域通過名單，共 {len(passed_course_ids_global)} 門課程 ---")
    # --- 1.6: (新) 建立一個集合，追蹤已加入「未通過」列表的課號 ---
    # 集合 2: 儲存已加入「未通過列表」的課號，避免重複
    failed_course_ids_added = set()

    # --- 2. 遍歷所有課程並計算 (第二階段) ---
    for course in all_courses:
        
        course_display_name = f"[課號: {course.get('課號')}] {course.get('課名')}"
        course_code = str(course.get('課號', '')).upper().strip()
        course_name = str(course.get('課名', ''))
        course_type = course.get("選別")
        score = course.get("得分")

        category_key = "其他" # 預設
        
        if course_type and ("共必" in course_type or "共同必修" in course_type):
            category_key = "共同必修"
        elif course_type and "通識" in course_type:
            category_key = "通識"
        elif course_type and "院必修" in course_type:
            category_key = "院必修"
        elif course_type and "選" in course_type: 
            category_key = "選修"
        elif course_type and "系必" in course_type: 
            category_key = "必修"

        if score == "通過":
            # ★ 修正點：防止重複計算相同課號的學分 (例如重修刷分)
            if course_code in passed_course_ids_audit:
                continue # 這門課已經算過學分了，跳過

            try:
                credits = float(course.get("學分", 0))
            except:
                credits = 0.0
            
            display_credits = int(credits) if credits.is_integer() else credits
            course_display_passed = f"{course_display_name} - {display_credits} 學分"
            
            audit_categories[category_key]["earned_sum"] += credits
            audit_categories[category_key]["earned_courses"].append(course_display_passed)
            total_earned_credits += credits # (新) 累加總學分

            # 標記這門課已經算過分了
            if course_code:
                passed_course_ids_audit.add(course_code)
            
            # ==========================================
            # ★ 核心修改：共同必修 4 大規則判斷
            # ==========================================
            
            # 規則 1: 英語 (10學分) -> 課號 LC 或 EL 開頭
            if course_code.startswith('LC') or course_code.startswith('EL'):
                common_req_status['English']['earned'] += credits
            
            # 規則 2: 國文 (4學分) -> 課號 CL 開頭
            elif course_code.startswith('CL'):
                common_req_status['Chinese']['earned'] += credits
            
            # 規則 3: 服務學習 (1學分) -> 課名包含 "服務"
            if "服務" in course_name:
                common_req_status['Service']['earned'] += credits
            # ==========================================
            if category_key == "通識" and course_code:
                for prefix in audit_categories["通識"]["core_required_prefixes"]:
                    if course_code.startswith(prefix):
                        audit_categories["通識"]["core_passed_prefixes"].add(prefix)
                        break
                        
        elif score == "未過":
            # --- (新) 檢查重修 & 重複被當 邏輯 ---
            
            # 檢查 1: 如果這門課「曾經通過」，就忽略這筆 "未過" 紀錄
            if course_code in passed_course_ids_global:
                continue 
            
            # 檢查 2: (如果沒通過) 檢查是否「已經加過」這門 "未過" 的課
            if course_code in failed_course_ids_added:
                continue # 已經加過了，忽略這筆重複的 "未過" 紀錄

            # --- (新) 符合條件：加入列表並標記 ---
            # 如果 1 和 2 都通過了 (代表這門課「從未通過」且「尚未被記錄」)
            audit_categories[category_key]["failed_courses"].append(course_display_name)
            
            # 標記此課號已加入「未通過」列表
            if course_code:
                failed_course_ids_added.add(course_code)
            # --- 邏輯結束 ---
            
    # --- 3. 結算「通識」核心 ---
    gen_ed = audit_categories["通識"]
    gen_ed["core_passed_count"] = len(gen_ed["core_passed_prefixes"])
    gen_ed["core_missing_prefixes"] = sorted(list(gen_ed["core_required_prefixes"] - gen_ed["core_passed_prefixes"]))
    gen_ed["is_core_complete"] = len(gen_ed["core_missing_prefixes"]) == 0
    # --- 4. (BUG 修正) 將 Set 轉換為 List 以便 JSON 序列化 ---
    gen_ed["core_required_prefixes"] = sorted(list(gen_ed["core_required_prefixes"]))
    gen_ed["core_passed_prefixes"] = sorted(list(gen_ed["core_passed_prefixes"]))
    
    # ==========================================
    # ★ 新增：結算共同必修缺額，並存入 audit_categories
    # ==========================================
    for data in common_req_status.values():
        data['gap'] = max(0, data['goal'] - data['earned'])
    
    # 存回去，讓前端或 AI 可以讀到
    audit_categories['Common_Requirements_Detail'] = common_req_status
    # ==========================================

    print("--- (2/3 - A) 審查計算完成 ---")
    
    # (新) 建立總計物件
    totals = {
        "total_earned": total_earned_credits,
        "total_required": total_required_credits
    }
    
    print("--- (2/3 - B) JSON 序列化準備完成 ---")
    return audit_categories, totals

# ======================================================================
# 
#                           PART 2.5: AI 建議生成 (新增功能)
# 
# ======================================================================

# ======================================================================
# 
#                           PART 3: Flask 伺服器
# 
# ======================================================================

app = Flask(__name__)
CORS(app) # 允許所有來源的前端呼叫此 API


# ==========================================
#  前端網頁路由 (使用 Template 模式)
# ==========================================

# 1. 根目錄路由：直接顯示登入頁
@app.route('/')
def root():
    # Flask 會自動去 templates 資料夾找 login.html
    return render_template('login.html')

# 2. 登入頁路由 (防止有人手動輸入網址)
@app.route('/login.html')
def login_page():
    return render_template('login.html')

# 3. 主頁路由 (對應前端 JS 的 window.location.href = 'index.html')
@app.route('/index.html')
def dashboard():
    return render_template('index.html')



# ==========================================
#  登入 API (支援轉系生/新使用者)
# ==========================================
@app.route("/api/login", methods=["POST"])
def handle_login():
    try:
        data = request.json
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({"success": False, "message": "請輸入學號"}), 400
            
        # 1. 先去資料庫找找看有沒有這個人
        user_info = check_user_exists(student_id)
        
        if user_info:
            # A. 老朋友：資料庫有資料
            return jsonify({
                "success": True, 
                "user": user_info
            })
        else:
            # B. 新朋友/轉系生：資料庫沒資料
            # ★ 關鍵修改：不要回傳 401 錯誤，而是讓他通過！
            # 我們給他一個暫時的身分，讓他能進去 index.html 上傳檔案
            return jsonify({
                "success": True, 
                "user": {
                    "id": student_id,
                    "name": "新同學",       # 暫時的稱呼
                    "department": "尚未驗證" # 暫時的系所
                }
            })
            
    except Exception as e:
        print(f"Login API Error: {e}")
        return jsonify({"success": False, "message": "系統錯誤"}), 500

# ==========================================
#  PDF 上傳與審查 API
# ==========================================
@app.route("/api/audit", methods=["POST"])
def handle_pdf_upload():
    """
    接收前端上傳的 PDF 檔案，執行解析和審查，並回傳 JSON 結果。
    """
    
    # 1. 檢查是否有檔案
    if 'pdf_file' not in request.files:
        return jsonify({"error": "找不到上傳的 PDF 檔案 (key 必須是 'pdf_file')"}), 400
        
    file = request.files['pdf_file']
    
    if file.filename == '':
        return jsonify({"error": "未選擇檔案"}), 400

    if file and file.filename.endswith('.pdf'):
        try:
            # 2. 建立一個「暫存」的 PDF 檔案
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                file.save(temp_pdf.name) # 將使用者上傳的資料存入暫存檔
                temp_pdf_path = temp_pdf.name # 取得這個暫存檔的「動態路徑」
            
            print(f"檔案已暫存於: {temp_pdf_path}")

            # 3. 呼叫 PDF 解析
            all_courses, student_info = parse_pdf_with_regex(temp_pdf_path) # (新) 接收學生資訊
            
            # =============== ↓↓↓ 您要求的新增程式碼 (儲存 JSON) ===============
            if all_courses: # 確保有抓到資料再儲存
                print("--- (新增步驟) 正在儲存解析結果到 JSON 檔案... ---")
                
                # 準備要儲存的資料
                debug_data = {
                    "student_info": student_info,
                    "all_courses": all_courses
                }
                
                # 定義檔案名稱 (存在腳本的同層目錄)
                output_filename = "_debug_parsed_data.json"
                
                try:
                    # 'w' - 寫入模式
                    # encoding='utf-8' - 確保中文不會亂碼
                    # ensure_ascii=False - 確保 json.dump 正確處理中文
                    # indent=4 - 讓 JSON 檔案格式化，易於閱讀
                    with open(output_filename, 'w', encoding='utf-8') as f:
                        json.dump(debug_data, f, ensure_ascii=False, indent=4)
                    print(f"--- (新增步驟) 成功儲存資料到 {output_filename} ---")
                except Exception as e:
                    print(f"[錯誤] 儲存 JSON 檔案時失敗: {e}")
            # =============== ↑↑↑ 新增程式碼結束 ↑↑↑ ===============

            if not all_courses:
                 # 清理暫存檔
                os.remove(temp_pdf_path)
                return jsonify({"error": "解析 PDF 失敗，或 Regex 未匹配到任何課程。"}), 500
            
            # 3. 寫入資料庫 (呼叫外部 save_to_db 模組)
            # 這是我們新加入的步驟，取代原本的 JSON 寫入
            if student_info.get('id'):
                print(f"--- (2/4) 正在呼叫資料庫存檔模組... ---")
                save_success = save_student_data(student_info, all_courses)
                if not save_success:
                    print("[警告] 資料庫寫入失敗，但流程將繼續進行畢業審查。")
            else:
                print("[警告] 無法取得學號，跳過資料庫存檔步驟。")
                
            # 4. 呼叫畢業審查
            audit_results, totals = calculate_graduation_audit(all_courses) # (新) 接收總計
       
            
            # 5. 清理暫存檔
            os.remove(temp_pdf_path)
            
            print("--- (3/3) 成功，準備回傳 JSON 給前端 ---")
            
            # 6. 將抓到的課程資料 (JSON) 回傳給前端
            return jsonify({
                "message": f"成功解析 {len(all_courses)} 筆課程",
                "audit_report": audit_results,
                "student_info": student_info, # (新)
                "totals": totals # (新)
            })

        except Exception as e:
            # (清理暫存檔 - 以防万一)
            if 'temp_pdf_path' in locals() and os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
            # (新) 提供更詳細的錯誤回報
            print(f"[嚴重錯誤] {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"處理 PDF 時發生嚴重錯誤: {e}"}), 500
    else:
        return jsonify({"error": "只接受 PDF 檔案"}), 400

# ... (上面的程式碼保持不變)

# ======================================================================
# 
#                           (新增) 對話問答 API
# 
# ======================================================================



@app.route("/api/chat", methods=["POST"])
def handle_chat():
    try:
        data = request.json
        user_message = data.get('message', '')
        student_id = data.get('student_id')

        if not user_message:
            return jsonify({"reply": "請輸入問題"}), 400

        # 1. 從資料庫撈取資料
        db_student_info, db_courses = get_student_data_from_db(student_id)
        if not db_student_info:
            return jsonify({"reply": "找不到資料"}), 404

        # 2. 進行畢業審查 (算已通過的)
        audit_results, totals = calculate_graduation_audit(db_courses)

        # ==========================================
        # ★ 新增：準備共同必修細項 Prompt
        # ==========================================
        common_detail = audit_results.get('Common_Requirements_Detail', {})
        common_req_str = ""
        if common_detail:
            # --- ↓↓↓ 修改這裡 ↓↓↓ ---
            # 1. 自動從 audit_results 抓取共同必修的目標值 (如果抓不到預設 15)
            common_goal = audit_results.get("共同必修", {}).get("goal", 15)
            
            # 2. 將變數放入字串，不再寫死數字
            common_req_str = f"\n【共同必修詳細檢核 (目標{common_goal}學分)】\n"
            # --- ↑↑↑ 修改結束 ↑↑↑ ---

            for key, info in common_detail.items():
                status = "✅ 已完成" if info['gap'] == 0 else f"❌ 尚缺 {info['gap']} 學分"
                common_req_str += f"- {info['name']}: 目標 {info['goal']}, 目前 {info['earned']} ({status})\n"
        # ==========================================

        # 3. 準備「完整修課紀錄」給 AI (包含所有已修、修習中)
        full_transcript_list = []
        current_taking_credits = 0
        
        for c in db_courses:
            year = c.get('學年', '0')
            score = c.get('分數')
            c_name = c.get('課名')
            c_type = c.get('選別', '')

            # === [修正點 1] 使用 float 避免 crash ===
            try:
                c_credit = float(c.get('學分', 0))
            except (ValueError, TypeError):
                c_credit = 0.0
            
            # 顯示優化 (3.0 -> 3)
            display_credit = int(c_credit) if c_credit.is_integer() else c_credit
            
            # === [修正點 2] 判斷分數狀態 ===
            # 如果分數是 None, 空字串, *, 或 'None'，視為修習中
            if not score or score in ['*', 'None', '']:
                grade_display = "修習中"
                # 只有修習中的才加入 "current_taking_credits"
                # (因為已通過的已經算在 earned 裡面了)
                current_taking_credits += c_credit
            else:
                grade_display = score

            # 格式： [112-1] 基礎程式設計 (系必/2學分, 89)
            # 格式： [113-2] 行動裝置程式設計 (選/3學分, 95)
            full_transcript_list.append(f"[{c['學年']}-{c['期']}] {c['課名']} ({display_credit}學分, {grade_display})")

        # 接成字串
        full_transcript_str = "\n".join(full_transcript_list) if full_transcript_list else "無修課紀錄"

        # 4. 準備數據
        earned = totals.get('total_earned', 0)
        required = totals.get('total_required', 128)
        # 剩餘學分 = 畢業門檻 - (已通過 + 正在修)
        remaining_credits = max(0, required - earned)
        
        # 必修重修清單
        failed_list = audit_results.get('必修', {}).get('failed_courses', [])
        unpassed_compulsory = ", ".join(failed_list) if failed_list else "目前無"

        gen_ed = audit_results.get('通識', {})
        missing_core = ", ".join(gen_ed.get('core_missing_prefixes', [])) if not gen_ed.get('is_core_complete') else "已完成"

        # === 建議：先在 Python 算好年級，不要讓 AI 算 ===
        import datetime
        current_ro_year = datetime.datetime.now().year - 1911
        try:
            enroll_year = int(db_student_info.get('year', 0))
            grade_level = current_ro_year - enroll_year + 1
            student_grade_str = f"大{grade_level}" if grade_level > 0 else "未知年級"
        except:
            student_grade_str = "未知年級"

        # === 精簡版 Prompt ===
        system_context = f"""
        你是資深、溫暖且說話精簡的大學學業輔導員。你的目標是解決問題，而非朗讀數據。

        【學生背景】
        - 姓名：{db_student_info.get('name')} ({student_grade_str})
        - 學分現況：已過 {earned} / 門檻 {required} (尚缺約 {remaining_credits})
        - 待補修必修：{unpassed_compulsory}
        - 通識缺漏：{missing_core}
        
        {common_req_str}
        【修課大數據 (僅供查閱，除非被問否則**嚴禁**直接貼出)】
        {full_transcript_str}

        【回答核心原則】
        1. **結論優先**：開頭直接講重點（例如：「進度不錯，只剩29學分」或「注意！有3門必修被當」）。
        2. **情境化建議**：
           - 問「規劃」：將剩餘學分平均分配到未來學期 (學分下限16)，避免單學期負擔過重。
           - 問「還差多少」：直接回答缺漏的具體領域。
           - 問「某學期修了什麼」：才去查閱上方清單回答。
        3. **語意理解**：
           - "1132" = "113-2"。
           - "未送分/修習中" 視為預計會拿到的學分，但在計算缺額時需說明。

        【排版格式鐵律 (必須遵守)】
        1. **條列式**：列舉項目時務必使用 Markdown (`-` 或 `1.`) 並**強制換行**。
           ❌ 錯誤：統計學(99)、線性代數(92)
           ✅ 正確：
              - 統計學 (99分)
              - 線性代數 (92分)
        2. **重點標示**：關鍵字（學分、不及格科目、學期）使用 **粗體**。

        請用繁體中文，像學長一樣給予溫暖且具體的建議。
        """

        # 3. 呼叫 Groq
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_context},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_completion_tokens=8192, # 稍微增加長度以容納解釋
            stream=False
        )
        
        return jsonify({"reply": completion.choices[0].message.content})

    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({"reply": "AI 暫時無法回應，請稍後再試。"}), 500
    
# ==========================================================
#  (新增) 獲取學生完整資料 API (用於登入後自動載入)
# ==========================================================
@app.route("/api/student/data", methods=["POST"])
def get_student_full_data():
    try:
        data = request.json
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({"error": "缺少學號"}), 400

        # 1. 從資料庫撈取資料 (使用現有的函式)
        db_student_info, db_courses = get_student_data_from_db(student_id)
        
        # 如果資料庫完全沒資料 (代表是第一次登入的新用戶)
        if not db_student_info:
            return jsonify({
                "found": False, 
                "message": "尚無資料，請上傳 PDF"
            })

        # 2. 進行畢業審查計算 (使用現有的函式)
        audit_results, totals = calculate_graduation_audit(db_courses)

        # 3. 回傳跟上傳 PDF 時完全一樣的 JSON 結構
        return jsonify({
            "found": True,
            "message": "成功載入舊資料",
            "student_info": db_student_info,
            "audit_report": audit_results,
            "totals": totals
        })

    except Exception as e:
        print(f"Fetch Data Error: {e}")
        return jsonify({"error": "系統錯誤"}), 500
    

# ... (原本的 if __name__ == "__main__": 保持不變)
# --- 程式執行入口 ---
if __name__ == "__main__":
    print("--- 正在啟動畢業審查後端伺服器 ---")
    print("--- 請在 http://127.0.0.1:5000 存取 ---")
    app.run(debug=True, port=5000)