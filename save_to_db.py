import mysql.connector
from mysql.connector import Error

# 資料庫連線設定
db_config = {
    'host': '127.0.0.1',
    'user': 'SADPython',      
    'password': '&Louis0811',  
    'database': 'sadpython',  
    'connection_timeout': 5,
    'use_pure': True
}

# ==========================================================
#  登入檢查函式：檢查學生是否存在於資料庫
# ==========================================================
def check_user_exists(student_id):
    print(f">>> [Login Check] 正在查詢學號: {student_id}")
    connection = None
    try:
        # 建立連線 (這裡會使用您檔案上方定義好的 db_config)
        connection = mysql.connector.connect(**db_config)
        
        # 使用 dictionary=True 讓回傳結果變成字典
        cursor = connection.cursor(dictionary=True)

        sql = "SELECT * FROM STUDENT WHERE StudentID = %s"
        cursor.execute(sql, (student_id,))
        user = cursor.fetchone()

        if user:
            print(f">>> 找到學生: {user['StudentName']}")
            # 回傳前端需要的資料格式
            return {
                "id": user['StudentID'],
                "name": user['StudentName'],
                "department": f"{user['Department']} {user['Major']}"
            }
        else:
            print(">>> 查無此人")
            return None

    except Error as e:
        print(f"!!! 資料庫查詢錯誤: {e}")
        return None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
# ==========================================================
#  1. 儲存函式：將學生資料與課程資料存入 MySQL
# ==========================================================
def save_student_data(student_info, all_courses):
    print(">>> [Debug] 進入 save_student_data 函式")
    connection = None
    try:
        print(f">>> [Debug] 嘗試連接 MySQL... (Host: {db_config['host']})")
        
        # 1. 建立連線
        connection = mysql.connector.connect(**db_config)
        
        if connection.is_connected():
            print(">>> [Debug] MySQL 連線成功！")
            cursor = connection.cursor()
            
            # 2. 寫入學生
            print(f">>> [Debug] 準備寫入學生: {student_info['id']}")
            raw_dept = student_info.get('department', '')
            parts = raw_dept.split()
            dept_name = "資訊管理學系"
            major_name = parts[0] if len(parts) > 0 else raw_dept
            status = parts[1] if len(parts) > 1 else "一般生"
            
            sql_student = """
            INSERT INTO STUDENT (StudentID, StudentName, EnrollmentYear, Department, Major, StudentStatus)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                StudentName = VALUES(StudentName),
                EnrollmentYear = VALUES(EnrollmentYear),
                Department = VALUES(Department),
                Major = VALUES(Major),
                StudentStatus = VALUES(StudentStatus);
            """
            cursor.execute(sql_student, (
                student_info['id'], 
                student_info['name'], 
                student_info['year'], 
                dept_name, 
                major_name, 
                status
            ))
            print(">>> [Debug] 學生資料寫入/更新完成")

            
            
            # 4. 寫入課程
            print(f">>> [Debug] 開始寫入 {len(all_courses)} 筆課程...")
            
            for i, course in enumerate(all_courses):
                # 每處理 10 筆印一次進度，避免卡住不知道
                if i % 10 == 0:
                    print(f"    處理第 {i} 筆...")

                course_id = course.get('課號')
                if not course_id: continue

                course_name = course.get('課名', '未知課程')
                credits = course.get('學分', 0)
                offering_dept = course_id[:2] if len(course_id) >= 2 else "OT"
                
                # 課程
                sql_course = "INSERT IGNORE INTO COURSE (CourseID, CourseName, Credits, OfferingDepartment) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql_course, (course_id, course_name, credits, offering_dept))

                # 修課紀錄
                semester_str = f"{course.get('學年')}-{course.get('期')}"
                is_passed = 1 if course.get('得分') == '通過' else 0
                
                sql_transcript = """
                INSERT INTO TRANSCRIPT 
                (StudentID, CourseID, Semester, Grade, IsPassed, CourseTypeAsTaken, Remarks, DepartmentType, Book, CumulativeCredits)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    Grade = VALUES(Grade),
                    IsPassed = VALUES(IsPassed),
                    CourseTypeAsTaken = VALUES(CourseTypeAsTaken),
                    Remarks = VALUES(Remarks),
                    DepartmentType = VALUES(DepartmentType),
                    Book = VALUES(Book),
                    CumulativeCredits = VALUES(CumulativeCredits);
                """
                cursor.execute(sql_transcript, (
                    student_info['id'], course_id, semester_str, course.get('分數'), is_passed,
                    course.get('選別'), course.get('說明'), course.get('系所'), course.get('冊'), course.get('累計')
                ))

            connection.commit()
            print(">>> [Debug] 全部完成！已 Commit。")
            return True

    except Error as e:
        print(f"!!! [嚴重錯誤] 資料庫操作失敗: {e}")
        return False
        
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
            print(">>> [Debug] 連線已關閉")

# ==========================================================
#  2. (新增) 讀取函式：給 AI 對話用
# ==========================================================
def get_student_data_from_db(student_id):
    """
    輸入學號，從 MySQL 撈取資料，並轉換回當初 PDF Parser 的 JSON 格式。
    Returns: (student_info, all_courses)
    """
    print(f">>> [Debug] 正在從資料庫讀取學號: {student_id}")
    connection = None
    try:
        connection = mysql.connector.connect(**db_config)
        if not connection.is_connected():
            return None, None

        cursor = connection.cursor(dictionary=True) # 使用 dictionary cursor 方便操作

        # 1. 讀取學生基本資料
        sql_student = "SELECT * FROM STUDENT WHERE StudentID = %s"
        cursor.execute(sql_student, (student_id,))
        student_row = cursor.fetchone()

        if not student_row:
            print(">>> [Debug] 查無此學生")
            return None, None

        # 組合 student_info (格式要跟 parse_pdf 回傳的一樣)
        student_info = {
            "id": student_row['StudentID'],
            "name": student_row['StudentName'],
            "year": student_row['EnrollmentYear'],
            # 這裡把系所和組別拼回來，例如 "資訊管理學系 商業智慧組"
            "department": f"{student_row['Department']} {student_row['Major']}" 
        }

        # 2. 讀取修課紀錄 (JOIN TRANSCRIPT 與 COURSE 以取得課名與學分)
        sql_courses = """
        SELECT 
            t.DepartmentType, -- 系所
            t.CourseID,       -- 課號
            t.Book,           -- 冊
            t.Semester,       -- 學期 (格式 110-1)
            c.CourseName,     -- 課名
            t.CourseTypeAsTaken, -- 選別
            t.IsPassed,       -- 通過狀態 (1/0)
            c.Credits,        -- 學分
            t.CumulativeCredits, -- 累計
            t.Grade,          -- 分數
            t.Remarks         -- 說明
        FROM TRANSCRIPT t
        JOIN COURSE c ON t.CourseID = c.CourseID
        WHERE t.StudentID = %s
        ORDER BY t.Semester DESC
        """
        cursor.execute(sql_courses, (student_id,))
        course_rows = cursor.fetchall()

        all_courses = []
        for row in course_rows:
            # 處理學期 (把 "110-1" 拆開)
            semester_parts = row['Semester'].split('-')
            year = semester_parts[0] if len(semester_parts) > 0 else ""
            term = semester_parts[1] if len(semester_parts) > 1 else ""

            # 處理通過狀態 (1 -> "通過", 0 -> "未過")
            score_status = "通過" if row['IsPassed'] == 1 else "未過"

            # === ★★★ 關鍵修正：處理 MySQL DECIMAL 轉型 ★★★ ===
            try:
                # 先轉 float 處理 Decimal 物件
                raw_c = float(row['Credits']) 
                # 如果是整數 (3.0)，轉成字串 "3"；否則轉成 "3.5"
                # 這樣後面的程式做 int("3") 就不會報錯了
                clean_credit = str(int(raw_c)) if raw_c.is_integer() else str(raw_c)
            except:
                clean_credit = "0"
            # ==================================================

            # 轉回 PDF Parser 的字典 Key 名稱 (中文 Key)
            course_dict = {
                "系所": row['DepartmentType'],
                "課號": row['CourseID'],
                "冊": row['Book'],
                "學年": year,
                "期": term,
                "課名": row['CourseName'],
                "選別": row['CourseTypeAsTaken'],
                "得分": score_status,
                "學分": clean_credit, # 轉字串以符合原始格式
                "累計": str(row['CumulativeCredits']),
                "分數": row['Grade'],
                "說明": row['Remarks']
            }
            all_courses.append(course_dict)

        print(f">>> [Debug] 成功讀取 {len(all_courses)} 筆課程資料")
        return student_info, all_courses

    except Error as e:
        print(f"!!! [讀取錯誤] 資料庫查詢失敗: {e}")
        return None, None
    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
            print(">>> [Debug] 連線已關閉")
