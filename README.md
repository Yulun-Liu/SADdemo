````markdown
# 🎓 大學畢業學分審查系統 (Graduation Audit System)

這是一個基於 Python Flask 與 MySQL 開發的 Web 應用程式，旨在協助學生自動化審查畢業學分。系統能夠解析學生的成績單 PDF 檔案，將修課紀錄與畢業門檻進行比對，並透過視覺化圖表呈現目前的學分進度。

此外，系統整合了 **AI 智慧助教 (Groq API)**，學生可以直接與 AI 對話，詢問關於修課規劃或缺修學分的問題。

## ✨ 主要功能 (Features)

* **📊 自動化學分計算**：上傳成績單 PDF，系統自動解析並計算必修、選修、通識等各類別學分。
* **📈 視覺化儀表板**：使用 Chart.js 繪製圓餅圖與進度條，學分完成度一目瞭然。
* **🤖 AI 學業諮詢室**：整合 Groq (LLM) 模型，提供個人化的學業建議與問答。
* **🔐 身分驗證系統**：
    * **舊生自動載入**：再次登入時自動撈取資料庫紀錄，無需重複上傳。
    * **新生/轉系生支援**：自動引導新使用者上傳 PDF 以建立學籍資料。
* **📱 響應式介面**：使用 Tailwind CSS 設計，支援電腦與行動裝置瀏覽。

## 🛠️ 技術棧 (Tech Stack)

### Backend (後端)
* **Python 3.x**
* **Flask** (Web Framework)
* **MySQL** (Database)
* **Groq API** (LLM Integration)
* **pdfplumber** (PDF Parsing)

### Frontend (前端)
* **HTML5 / JavaScript (ES6)**
* **Tailwind CSS** (Styling)
* **Chart.js** (Data Visualization)
* **Marked.js** (Markdown Rendering)

## 📂 專案結構 (Project Structure)

```text
graduation-audit-system/
├── app.py                 # Flask 主程式 (API 路由與核心邏輯)
├── save_to_db.py          # PDF 解析與資料庫存取邏輯
├── init_students.py       # 資料庫初始化腳本
├── requirements.txt       # 專案依賴套件列表
├── .env                   # 環境變數 (API Key, DB Config)
└── templates/             # 前端頁面
    ├── login.html         # 登入頁面
    └── index.html         # 主儀表板頁面
````

## 🚀 安裝與執行教學 (Installation)

### 1\. 下載專案

```bash
git clone [https://github.com/YourUsername/Your-Project-Name.git](https://github.com/YourUsername/Your-Project-Name.git)
cd Your-Project-Name
```

### 2\. 安裝依賴套件

建議使用虛擬環境 (Virtual Environment)。

```bash
pip install -r requirements.txt
```

### 3\. 設定環境變數 (.env)

請在根目錄建立 `.env` 檔案，並填入以下資訊：

```ini
GROQ_API_KEY=your_groq_api_key_here
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=graduation_system
```

### 4\. 初始化資料庫

確保 MySQL 服務已啟動，並建立好 `graduation_system` 資料庫，然後執行：

```bash
python init_students.py
```

### 5\. 啟動伺服器

```bash
python app.py
```

看到 `Running on http://127.0.0.1:5000` 即代表啟動成功。

## 📖 使用說明 (Usage)

1.  開啟瀏覽器前往 `http://127.0.0.1:5000`。
2.  **登入**：輸入學號（例如：`1121726`）。
      * 若為**首次使用者**，系統會提示您上傳 PDF 成績單。
      * 若為**已建檔學生**，系統將直接顯示目前的學分進度圖表。
3.  **上傳 PDF**：點擊左側「上傳 PDF」按鈕，選擇學校匯出的成績單檔案。
4.  **AI 諮詢**：在右側的對話框輸入問題（例如：「我還差多少通識學分？」），AI 將根據您的資料回答。

## 🤝 貢獻與開發 (Contributing)

歡迎 Fork 此專案並提交 Pull Request。如有任何問題，請開立 Issue 討論。

## 📝 License

This project is licensed under the MIT License.

````

***

### 💡 補充說明：如何建立 `requirements.txt`

為了讓上面的安裝教學有效，您需要在專案資料夾中產生一個 `requirements.txt` 檔案，列出您用到的套件。

您可以在終端機輸入以下指令自動產生（如果您有用虛擬環境）：
```bash
pip freeze > requirements.txt
````

或者，您可以手動建立一個 `requirements.txt` 檔案，內容大概是這樣（根據我們這幾天用到的）：

```text
Flask
mysql-connector-python
groq
python-dotenv
pdfplumber
```

把這份 README 放上去後，您的 GitHub 專案看起來就會非常專業了！祝您專案順利！ 🚀