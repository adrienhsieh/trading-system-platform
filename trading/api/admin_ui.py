import os
import sqlite3
from flask import Blueprint, render_template_string, request, session, redirect, Response

# 1. 建立融入您專案的後台藍圖
admin_bp = Blueprint("opus_admin_gate", __name__, url_prefix="/admin")

# 2. 精準對準專案根目錄
CURRENT_FILE_DIR = os.path.dirname(os.path.abspath(__file__)) 
PROJECT_ROOT_DIR = os.path.abspath(os.path.join(CURRENT_FILE_DIR, "..", "..")) 

DB_MAP = {
    "trading_system": {"path": os.path.join(PROJECT_ROOT_DIR, "trading_system.db").replace("\\", "/"), "name": "⚙️ 設定庫"},
    "intelligence":   {"path": os.path.join(PROJECT_ROOT_DIR, "intelligence.db").replace("\\", "/"), "name": "🧠 AI庫"},
    "ohlcv_cache":    {"path": os.path.join(PROJECT_ROOT_DIR, "ohlcv_cache.db").replace("\\", "/"), "name": "📈 行情庫"},
    "positions":      {"path": os.path.join(PROJECT_ROOT_DIR, "positions.db").replace("\\", "/"), "name": "💼 部位庫"}
}

def query_db(db_path, sql, args=(), fetchall=True):
    """底層資料庫安全引擎"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    try:
        cursor.execute(sql, args)
        if sql.strip().upper().startswith("SELECT") or "PRAGMA" in sql.upper() or sql.strip().upper().startswith("WITH"):
            res = cursor.fetchall() if fetchall else cursor.fetchone()
        else:
            conn.commit()
            res = f"影響行數: {cursor.rowcount}"
        return res, cursor.description, None
    except Exception as e:
        return None, None, str(e)
    finally:
        conn.close()

# 3. 🛡️ 自訂管理員安全驗證（HTTP Basic Auth，避免密鑰衝突）
def check_auth(username, password):
    return username == "admin" and password == "admin123"

def authenticate():
    return Response(
        "🔮 交易主控台安全驗證：請輸入正確的帳號密碼。\n", 
        401, 
        {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )

@admin_bp.before_app_request
def security_filter():
    if request.path.startswith("/admin"):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()

# 4. 核心主控制台（前半段：100% 精準元組拆包，徹底洗淨欄位名稱）
# 4. 核心主控制台（前半段：100% 精準元組拆包，徹底洗淨欄位名稱）
@admin_bp.route("/", methods=["GET", "POST"])
def admin_console():
    # 💡 1. 嚴格鎖定頂部按鈕 Session
    current_db_key = session.get("current_opus_db", "intelligence")
    if current_db_key not in DB_MAP: 
        current_db_key = "intelligence"
        
    current_db_path = DB_MAP[current_db_key]["path"]
    
    # 讀取當前資料表清單
    tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    tables_res, _, _ = query_db(current_db_path, tables_query)
    table_list = [row["name"] for row in tables_res] if tables_res else []

    # 狀態與頁籤追蹤紀錄
    active_table = request.args.get("table", "").strip()
    current_tab = request.args.get("tab", request.form.get("tab", "1")).strip()

    # 💡 智慧首表自動對齊引擎
    if not active_table and table_list:
        active_table = table_list[0]

    # 安全防禦：防範跨庫殘留異常
    if active_table and active_table not in table_list:
        active_table = table_list[0] if table_list else ""

    edit_pk_val = request.args.get("edit_pk", "")
    edit_schema_col = request.args.get("edit_schema_col", "")
    
    if edit_schema_col: current_tab = "1"
    if edit_pk_val: current_tab = "2"

    # 優先拿表單送出的 SQL，若沒有且點擊了 Table，則自動組裝預設 SELECT 查詢
    sql_input = request.form.get("sql", "").strip()
    if not sql_input and active_table:
        sql_input = f"SELECT * FROM {active_table} LIMIT 50;"

    # 如果是使用者點擊「執行 SQL 指令」送出表單（POST），後端強制重新導向鎖定在第 3 頁
    if request.method == "POST" and request.form.get("sql"):
        current_tab = "3"

    query_results = None
    column_names = []
    sql_error = None
    success_msg = session.pop("action_success", None)

    # 驅動底層安全引擎執行 SQL 查詢
    if sql_input and not sql_input.startswith("SELECT * FROM  LIMIT"):
        res, desc, err = query_db(current_db_path, sql_input)
        if err: 
            sql_error = err
        else:
            query_results = res
            # 💡 終極核心修正：d 是一個元組描述，精準取其第 0 項 d[0]，防範 IndexError
            if desc:
                column_names = [str(d[0]) if isinstance(d, (tuple, list)) else str(d) for d in desc]
    else:
        sql_input = ""

    # 在後端將第三頁籤的結果表格安全拼裝，將可能發生的 IndexError 阻斷在 Python 層
    sql_tab_result_html = ""
    if current_tab == "3" and sql_error:
        sql_tab_result_html = f'<div class="alert alert-danger font-monospace small mt-2">❌ SQL 執行失敗: {sql_error}</div>'
    elif current_tab == "3" and query_results is not None:
        if isinstance(query_results, str):
            sql_tab_result_html = f'<div class="alert alert-success small mt-3">✔️ {query_results}</div>'
        elif len(query_results) == 0:
            sql_tab_result_html = '<div class="alert alert-warning small mt-2">⚪ 查詢成功，但此語法沒有回傳 any 數據列。</div>'
        elif column_names:
            try:
                th_tags = "".join([f"<th>{c}</th>" for c in column_names])
                tr_tags = ""
                for r in query_results:
                    row_keys = {str(k).lower(): k for k in r.keys()} if hasattr(r, 'keys') else {}
                    td_tags = ""
                    for c in column_names:
                        target_key = row_keys.get(c.lower(), c)
                        try: val = r[target_key]
                        except: val = ""
                        td_tags += f"<td>{str(val) if val is not None else ''}</td>"
                    tr_tags += f"<tr>{td_tags}</tr>"
                
                sql_tab_result_html = f"""
                <div class="table-responsive shadow-sm rounded border border-secondary mt-3" style="max-height: 300px; overflow-y: auto; overflow-x: auto;">
                    <table class="table table-dark table-striped table-hover table-bordered small m-0">
                        <thead class="table-secondary text-dark sticky-top"><tr>{th_tags}</tr></thead>
                        <tbody>{tr_tags}</tbody>
                    </table>
                </div>"""
            except Exception as e:
                sql_tab_result_html = f'<div class="alert alert-danger small mt-2">❌ 前端渲染異常攔截: {str(e)}</div>'

    # 💡 智慧新增：每次渲染前，後端主動載入最新、最即時的 config.json 本地檔案內容
    raw_config_content = ""
    try:
        config_file_path = os.path.join(PROJECT_ROOT_DIR, "config.json")
        if os.path.exists(config_file_path):
            with open(config_file_path, "r", encoding="utf-8") as f:
                raw_config_content = f.read()
        else:
            raw_config_content = "{\n    \"message\": \"在專案根目錄找不到 config.json 檔案，請確認檔案位置！\"\n}"
    except Exception as ce:
        raw_config_content = f"{{\n    \"error\": \"讀取失敗\",\n    \"message\": \"{str(ce)}\"\n}}"
    # --- 🛠️ 區塊 A：資料表結構定義與穩定行內異動引擎 ---
    schema_html = ""
    pk_column = None
    
    if active_table:
        pragma_sql = f"PRAGMA table_info({active_table});"
        pragma_res, _, _ = query_db(current_db_path, pragma_sql)
        
        if pragma_res:
            schema_rows = ""
            for r in pragma_res:
                try: r_name = r["name"]
                except:
                    try: r_name = r["NAME"]
                    except: r_name = r
                    
                try: r_type = r["type"]
                except:
                    try: r_type = r["TYPE"]
                    except: r_type = r
                    
                try: r_notnull = r["notnull"]
                except:
                    try: r_notnull = r["NOTNULL"]
                    except: r_notnull = r
                    
                try: r_dflt = r["dflt_value"]
                except:
                    try: r_dflt = r["DFLT_VALUE"]
                    except: r_dflt = r
                    
                try: r_pk = r["pk"]
                except:
                    try: r_pk = r["PK"]
                    except: r_pk = r
                
                is_pk = "⭐ YES" if r_pk else "NO"
                if r_pk: pk_column = r_name
                
                is_editing_this_col = (edit_schema_col and edit_schema_col == r_name)
                
                if is_editing_this_col:
                    schema_rows += f"""
                    <tr>
                        <td><input type="text" name="n_name" value="{r_name}" class="form-control form-control-sm bg-dark text-white border-primary" form="schema_edit_form" required></td>
                        <td>
                            <select name="n_type" class="form-select form-select-sm bg-dark text-white border-primary" form="schema_edit_form">
                                <option value="TEXT" {"selected" if r_type=='TEXT' else ""}>TEXT</option>
                                <option value="INTEGER" {"selected" if r_type=='INTEGER' else ""}>INTEGER</option>
                                <option value="REAL" {"selected" if r_type=='REAL' else ""}>REAL</option>
                                <option value="BLOB" {"selected" if r_type=='BLOB' else ""}>BLOB</option>
                            </select>
                        </td>
                        <td>
                            <select name="n_notnull" class="form-select form-select-sm bg-dark text-white border-primary" form="schema_edit_form">
                                <option value="0" {"selected" if not r_notnull else ""}>NULL</option>
                                <option value="1" {"selected" if r_notnull else ""}>❌ NOT NULL</option>
                            </select>
                        </td>
                        <td><input type="text" name="n_dflt" value="{r_dflt if r_dflt is not None else ''}" placeholder="無" class="form-control form-control-sm bg-dark text-white border-primary" form="schema_edit_form"></td>
                        <td class="text-warning">{is_pk}</td>
                        <td class="text-center">
                            <button type="submit" form="schema_edit_form" class="btn btn-xs btn-primary fw-bold py-1 px-2 me-1">💾 儲存</button>
                            <a href="/admin/?table={active_table}&tab=1" class="btn btn-xs btn-outline-secondary py-1 px-2">取消</a>
                        </td>
                    </tr>"""
                else:
                    schema_rows += f"""
                    <tr>
                        <td><code>{r_name}</code></td>
                        <td><span class="badge bg-secondary">{r_type}</span></td>
                        <td>{'❌ NOT NULL' if r_notnull else 'NULL'}</td>
                        <td>{r_dflt if r_dflt is not None else '<span class="text-muted">None</span>'}</td>
                        <td class="text-warning">{is_pk}</td>
                        <td class="text-center">
                            <a href="/admin/?table={active_table}&edit_schema_col={r_name}&tab=1" class="btn btn-xs btn-outline-warning py-0 px-2 fw-bold me-1">✏️ 編輯結構</a>
                            <a href="/admin/schema/drop_col?table={active_table}&col={r_name}" 
                               class="btn btn-xs btn-outline-danger py-0 px-2 fw-bold"
                               onclick="return confirm('警告：確定要徹底刪除「{r_name}」欄位嗎？數據將無法恢復！');">❌ 刪除</a>
                        </td>
                    </tr>"""
            
            schema_html = f"""
            <form id="schema_edit_form" method="POST" action="/admin/schema/edit_col_submit?table={active_table}&old_col={edit_schema_col}"></form>
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="text-info fw-bold m-0">📋 資料表結構定義與異動：{active_table}</h6>
                <form method="POST" action="/admin/schema/add_col?table={active_table}" class="row g-2 align-items-center m-0">
                    <div class="col-auto"><input type="text" name="new_col_name" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="新欄位名稱" required></div>
                    <div class="col-auto">
                        <select name="new_col_type" class="form-select form-select-sm bg-dark text-white border-secondary">
                            <option value="TEXT">TEXT (字串)</option>
                            <option value="INTEGER">INTEGER (整數)</option>
                            <option value="REAL">REAL (浮點數)</option>
                            <option value="BLOB">BLOB (二進制)</option>
                        </select>
                    </div>
                    <div class="col-auto"><button type="submit" class="btn btn-info btn-sm fw-bold">➕ 新增欄位</button></div>
                </form>
            </div>
            <table class="table table-dark table-sm table-bordered m-0" style="font-size: 13px;">
                <thead class="table-info text-dark"><tr><th>欄位名稱</th><th>資料型態</th><th>空值約束</th><th>預設值</th><th>主鍵判定</th><th class="text-center">結構異動管理</th></tr></thead>
                <tbody>{schema_rows}</tbody>
            </table>"""

     # --- 📊 區塊 B：渲染數據內容與一鍵增刪改的數據視窗 ---
    results_table_html = ""
    if sql_error:
        if current_tab == "2":
            results_table_html = f'<div class="alert alert-danger font-monospace small">❌ SQL 錯誤: {sql_error}</div>'
    elif query_results is not None:
        if isinstance(query_results, str):
            results_table_html = f'<div class="alert alert-success small">✔️ {query_results}</div>'
        elif len(query_results) == 0:
            results_table_html = '<div class="alert alert-warning small">⚪ 查詢成功，但目前沒有任何數據。</div>'
        else:
            insert_form_html = ""
            if active_table and pk_column:
                fields_inputs = "".join([
                    f"""
                    <div style="display: flex; flex-direction: column; min-width: 110px; flex: 1;">
                        <label class="text-muted fw-bold mb-1" style="font-size: 11px;">{col}</label>
                        <input type="text" name="val_{col}" class="form-control form-control-sm bg-dark text-white" 
                               style="border: 1px solid #45475a;"
                               {"placeholder='(自增主鍵)' disabled" if col==pk_column else ""}>
                    </div>
                    """ 
                    for col in column_names
                ])
                insert_form_html = f"""
                <div class="p-3 mb-4 rounded shadow-sm" style="background-color: #11111b; border: 1px solid #a6e3a1;">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <h6 class="text-success fw-bold m-0" style="font-size: 13px;">➕ 快速追加新數據至 {active_table}</h6>
                        <button type="submit" form="master_insert_form" class="btn btn-success btn-sm fw-bold px-4 shadow">⚡ 送出新增</button>
                    </div>
                    <form id="master_insert_form" method="POST" action="/admin/insert?table={active_table}">
                        <div style="display: flex; flex-direction: row; flex-wrap: wrap; gap: 12px; align-items: flex-end;">
                            {fields_inputs}
                        </div>
                    </form>
                </div>"""
                
            thead = "".join([f'<th style="min-width: 110px; {"min-width: 350px;" if col=="summary" else ""} text-align: left; padding: 10px;">{col}</th>' for col in column_names]) + ( '<th style="width: 130px; min-width: 130px; text-align: center; position: sticky; right: 0; background: #343a40 !important; color: #fff; z-index: 15; box-shadow: -2px 0 5px rgba(0,0,0,0.3);">數據異動項目</th>' if pk_column else "" )
            
            form_wrapper_start = f'<form id="edit_form" method="POST" action="/admin/update?table={active_table}&pk_col={pk_column}&pk_val={edit_pk_val}">' if edit_pk_val else ''
            form_wrapper_end = '</form>' if edit_pk_val else ''
            
            tbody = ""
            modal_overlay_html = ""
            
            for row in query_results:
                row_keys_map = {str(k).lower(): k for k in row.keys()} if hasattr(row, 'keys') else {}
                pk_target_key = row_keys_map.get(str(pk_column).lower(), pk_column) if pk_column else None
                try: pk_val = str(row[pk_target_key]) if pk_target_key else None
                except: pk_val = None
                
                is_editing_this_row = (pk_val and edit_pk_val and pk_val == str(edit_pk_val))

                tbody += "<tr>"
                for col in column_names:
                    curr_key = row_keys_map.get(col.lower(), col)
                    try: val_data = str(row[curr_key]) if row[curr_key] is not None else ""
                    except: val_data = ""
                    if col == "summary":
                        tbody += f'<td style="white-space: normal; word-break: break-all; min-width: 350px; text-align: justify; padding: 8px;">{val_data}</td>'
                    else:
                        tbody += f'<td style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 8px 12px; text-align: center;">{val_data}</td>'
                
                if pk_column and pk_column in column_names:
                    tbody += f"""
                    <td class="text-center" style="position: sticky; right: 0; background: #181825; z-index: 12; border-left: 2px solid #313244 !important; white-space: nowrap; padding: 8px; box-shadow: -3px 0 6px rgba(0,0,0,0.4);">
                        <a href="#modal-{pk_val}" class="btn btn-xs btn-outline-warning py-1 px-2 fw-bold me-1">✏️ 編輯</a>
                        <a href="/admin/delete?table={active_table}&pk_col={pk_column}&pk_val={pk_val}" 
                           class="btn btn-xs btn-outline-danger py-1 px-2 fw-bold" 
                           onclick="return confirm('確定要刪除主鍵為 {pk_val} 的紀錄嗎？');">❌ 刪除</a>
                    </td>"""
                tbody += "</tr>"

                if pk_column and pk_column in column_names:
                    modal_inputs = ""
                    for col in column_names:
                        curr_key = row_keys_map.get(col.lower(), col)
                        try: val_data = str(row[curr_key]) if row[curr_key] is not None else ""
                        except: val_data = ""
                        
                        if col == pk_column:
                            modal_inputs += f'<div class="mb-3"><label class="form-label text-muted fw-bold small">{col} (主鍵)</label><input type="text" name="val_{col}" value="{val_data}" class="form-control form-control-sm bg-secondary text-dark" readonly></div>'
                        elif col == "summary":
                            modal_inputs += f'<div class="mb-3"><label class="form-label text-info fw-bold small">{col}</label><textarea name="val_{col}" class="form-control bg-dark text-white border-secondary" rows="4">{val_data}</textarea></div>'
                        else:
                            modal_inputs += f'<div class="mb-3" style="width: calc(50% - 6px);"><label class="form-label text-white small">{col}</label><input type="text" name="val_{col}" value="{val_data}" class="form-control form-control-sm bg-dark text-white border-secondary"></div>'
                    
                    modal_overlay_html += f"""
                    <div id="modal-{pk_val}" class="custom-modal-backdrop">
                        <div class="custom-modal-card p-4 rounded-3 shadow-lg card-editor">
                            <div class="d-flex justify-content-between align-items-center mb-3 border-bottom border-secondary pb-2">
                                <h5 class="text-warning fw-bold m-0" style="font-size:16px;">✏️ 編輯數據資料項目 (主鍵: {pk_val})</h5>
                                <a href="#consoleTab" class="btn-close btn-close-white text-decoration-none"></a>
                            </div>
                            <form method="POST" action="/admin/update?table={active_table}&pk_col={pk_column}&pk_val={pk_val}">
                                <div style="display: flex; flex-direction: row; flex-wrap: wrap; gap: 12px;">
                                    {modal_inputs}
                                </div>
                                <div class="text-end border-top border-secondary pt-3 mt-2">
                                    <a href="#consoleTab" class="btn btn-sm btn-outline-secondary me-2 px-3">取消</a>
                                    <button type="submit" class="btn btn-sm btn-primary fw-bold px-4 shadow">💾 儲存修改</button>
                                </div>
                            </form>
                        </div>
                    </div>"""
            
            results_table_html = f"""
            {insert_form_html}
            {form_wrapper_start}
            <div class="table-responsive shadow-sm rounded border border-secondary" style="max-height: 550px; overflow-y: auto; overflow-x: auto; white-space: nowrap;">
                <table class="table table-dark table-striped table-hover table-bordered small m-0" style="table-layout: auto; width: max-content; min-width: 100%;">
                    <thead class="table-secondary text-dark sticky-top" style="z-index: 16;"><tr>{thead}</tr></thead>
                    <tbody>{tbody}</tbody>
                </table>
            </div>
            {form_wrapper_end}
            {modal_overlay_html}"""

    # 💡 狀態與活性外提預處理：全面加入第 4 頁籤 (全局設定) 的顯示控制變數
    tab1_display = "block" if current_tab == "1" else "none"
    tab2_display = "block" if current_tab == "2" else "none"
    tab3_display = "block" if current_tab == "3" else "none"
    tab4_display = "block" if current_tab == "4" else "none"
    
    tab1_active = "active" if current_tab == "1" else ""
    tab2_active = "active" if current_tab == "2" else ""
    tab3_active = "active" if current_tab == "3" else ""
    tab4_active = "active" if current_tab == "4" else ""

    buttons_html = "".join([
        f'<a href="/admin/switch/{key}" class="btn {"btn-success fw-bold border-light shadow" if key == current_db_key else "btn-outline-secondary text-white"} me-2">{"🟢 " if key == current_db_key else "⚪ "}{info["name"]}</a>'
        for key, info in DB_MAP.items()
    ])

    tables_html = "".join([
        f'<a href="/admin/?table={t}&tab={current_tab}" class="list-group-item list-group-item-action bg-dark text-info border-secondary py-2 small fw-bold mb-2 rounded text-start w-100 {"active-table" if t == active_table else ""}" style="border: 1px solid #313244 !important; color: {"#a6e3a1" if t == active_table else "#89b4fa"} !important; display: block;">📊 {t}</a>'
        for t in table_list
    ])                    
    return render_template_string(f"""
    <!DOCTYPE html><html><head><title>交易系統核心主控台</title>
    <link href="https://cloudflare.com" rel="stylesheet">
    <style>
        body {{ background-color: #1e1e2e; color: #cdd6f4; font-family: sans-serif; height: 100vh; display: flex; flex-direction: column; margin: 0; padding: 0; overflow: hidden; }}
        .header-bar {{ background-color: #11111b; border-bottom: 2px solid #313244; padding: 15px 30px; flex-shrink: 0; }}
        .workspace {{ display: flex; flex-direction: row; flex-grow: 1; height: calc(100vh - 82px); overflow: hidden; }}
        .sidebar {{ background-color: #11111b; border-right: 2px solid #313244; width: 280px; flex-shrink: 0; overflow-y: auto; padding: 20px; }}
        .main-content {{ flex-grow: 1; overflow-y: auto; padding: 25px; background-color: #1e1e2e; position: relative; }}
        .card-editor {{ background-color: #181825; border: 1px solid #313244; }}
        textarea {{ font-family: monospace; background-color: #1e1e2e !important; color: #a6e3a1 !important; border: 1px solid #45475a !important; }}
        .active-table {{ background-color: #313244 !important; border-color: #a6e3a1 !important; }}
        .btn-xs {{ font-size: 11px; padding: 2px 6px; }}
        
        .table-responsive::-webkit-scrollbar {{ height: 10px; width: 10px; }}
        .table-responsive::-webkit-scrollbar-track {{ background: #11111b; }}
        .table-responsive::-webkit-scrollbar-thumb {{ background: #45475a; border-radius: 5px; }}
        .table-responsive::-webkit-scrollbar-thumb:hover {{ background: #585b70; }}

        /* 💡 橫向一字排開 四大 Chrome 級分頁標籤 */
        .chrome-tabs {{ border-bottom: 2px solid #313244 !important; gap: 6px; width: 100%; display: flex !important; flex-direction: row !important; list-style-type: none !important; padding-left: 0 !important; margin-bottom: 24px !important; }}
        .chrome-item {{ list-style-type: none !important; margin: 0 !important; padding: 0 !important; }}
        .chrome-link {{ background: none; color: #89b4fa; border: 1px solid #313244; border-bottom: none; font-weight: bold; padding: 10px 20px; border-top-left-radius: 6px; border-top-right-radius: 6px; cursor: pointer; display: block; text-decoration: none; transition: all 0.1s ease-in-out; user-select: none; }}
        .chrome-link:hover {{ background-color: #313244; color: #f5e0dc; }}
        .chrome-link.active {{ background-color: #181825 !important; color: #a6e3a1 !important; border-color: #313244 #313244 #181825 !important; box-shadow: 0 -2px 5px rgba(0,0,0,0.2); }}
        
        /* 💡 物理平級隔離類別：徹底移除 !important 霸凌，交由後端 display 純變數精確控制 */
        .custom-tab-panel {{ display: none; }}

        /* 💡 彈出遮罩視窗 (Modal) 物理核心樣式 */
        .custom-modal-backdrop {{
            position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
            background-color: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px);
            z-index: 9999; display: none; align-items: center; justify-content: center;
        }}
        .custom-modal-backdrop:target {{
            display: flex !important;
        }}
        .custom-modal-card {{
            width: 650px; max-width: 90%; max-height: 85vh; overflow-y: auto;
            border: 2px solid #f9e2af !important; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }}
    </style>
    </head>
    <body>
        <div class="header-bar d-flex justify-content-between align-items-center shadow">
            <h4 class="fw-bold m-0 text-white">⚔️ 交易系統核心多資料庫戰情室</h4>
            <div>{buttons_html}</div>
        </div>
        <div class="workspace">
            <div class="sidebar">
                <h5 class="text-white fw-bold mb-3 pb-2 border-bottom border-secondary" style="font-size:16px;">📂 結構資料表 ({len(table_list)})</h5>
                <div class="list-group rounded shadow-sm w-100">{tables_html}</div>
            </div>
            <div class="main-content">
                {f'<div class="alert alert-success p-2 small">✔️ {success_msg}</div>' if success_msg else ''}
                
                <!-- 💡 四大天王橫向 Chrome 分頁選單連結 -->
                <ul class="chrome-tabs" id="consoleTab">
                    <li class="chrome-item">
                        <a href="/admin/?table={active_table}&tab=1" class="chrome-link {tab1_active}">📋 (1) 表結構定義與異動</a>
                    </li>
                    <li class="chrome-item">
                        <a href="/admin/?table={active_table}&tab=2" class="chrome-link {tab2_active}">📊 (2) 數據視窗 & 新增單筆</a>
                    </li>
                    <li class="chrome-item">
                        <a href="/admin/?table={active_table}&tab=3" class="chrome-link {tab3_active}">📝 (3) SQL 編輯與控制區</a>
                    </li>
                    <li class="chrome-item">
                        <a href="/admin/?table={active_table}&tab=4" class="chrome-link {tab4_active}">⚙️ (4) 全局設定 config.json</a>
                    </li>
                </ul>

                <!-- 💡 頁籤面板內容儲存槽（完全隔離，100% 聽從後端純變數開關控制） -->
                <div class="tab-content" id="consoleTabContent">
                    
                    <!-- 📋 (1) 表結構定義與異動 面板 -->
                    <div style="display: {tab1_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
                        {schema_html if schema_html else '<div class="text-muted small py-3">⚪ 無可用的資料表結構。</div>'}
                    </div>
                    
                    <!-- 📊 (2) 數據視窗 & 新增單筆 面板 -->
                    <div style="display: {tab2_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
                        {results_table_html if results_table_html else '<div class="text-muted small py-3">⚪ 無可用的加載數據。</div>'}
                    </div>
                    
                    <!-- 📝 (3) SQL 編輯與控制區 面板 -->
                    <div style="display: {tab3_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
                        <form method="POST" action="/admin/?table={active_table}">
                            <input type="hidden" name="db" value="{current_db_key}">
                            <input type="hidden" name="tab" value="3">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <h5 class="text-success m-0 fw-bold">📝 全域 SQL 指令編譯器</h5>
                                <span class="badge bg-danger font-monospace">ACTIVE: {current_db_key}.db</span>
                            </div>
                            <div class="mb-3">
                                <textarea id="sql_editor" name="sql" class="form-control" rows="5">{sql_input}</textarea>
                            </div>
                            <div class="text-end mb-3">
                                <button type="submit" class="btn btn-primary fw-bold px-5 shadow">⚡ 執行 SQL 指令</button>
                            </div>
                        </form>
                        
                        {sql_tab_result_html}
                    </div>

                    <!-- ⚙️ (4) 全局設定 config.json 面板 -->
                    <div style="display: {tab4_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h5 class="text-warning m-0 fw-bold">⚙️ 交易系統全局 config.json 即時編譯主控卡</h5>
                            <button type="button" onclick="saveGlobalConfigJson()" class="btn btn-warning btn-sm fw-bold px-4 shadow">💾 儲存全局配置</button>
                        </div>
                        <div id="config_alert_zone"></div>
                        <div class="mb-3">
                            <!-- 💡 專屬黑客橘代碼編譯外觀文字域 -->
                            <textarea id="config_json_editor" class="form-control font-monospace p-3" rows="15" 
                                      style="background-color: #11111b !important; color: #fab387 !important; border: 1px solid #fab387 !important; font-size: 14px; line-height: 1.5;">{raw_config_content}</textarea>
                        </div>
                        
                        <!-- 💡 聯動獨立外部 Blueprint API 機制，即時攔截 JSON 語法錯誤而不白屏 -->
                        <script>
                            async function saveGlobalConfigJson() {{
                                const jsonStr = document.getElementById("config_json_editor").value;
                                const alertZone = document.getElementById("config_alert_zone");
                                alertZone.innerHTML = '<div class="alert alert-info py-2 small">正在進行安全性格式審查與磁碟寫入...</div>';
                                
                                try {{
                                    // 對齊並調用先前在 trading/api/user_config.py 部署的 /update_config 接口
                                    const response = await fetch('/api/user_page_config/update_config', {{
                                        method: 'POST',
                                        headers: {{ 'Content-Type': 'application/json' }},
                                        body: JSON.stringify({{ "config_json_str": jsonStr }})
                                    }});
                                    const result = await response.json();
                                    if (result.ok) {{
                                        alertZone.innerHTML = '<div class="alert alert-success py-2 small">✔️ ' + result.message + '</div>';
                                        setTimeout(() => {{ alertZone.innerHTML = ''; }}, 4000);
                                    }} else {{
                                        alertZone.innerHTML = '<div class="alert alert-danger py-2 small">❌ ' + result.error + '<br><span class="font-monospace text-light">' + result.message + '</span></div>';
                                    }}
                                }} catch(e) {{
                                    alertZone.innerHTML = '<div class="alert alert-danger py-2 small">❌ 連線通訊異常: ' + e + '</div>';
                                }}
                            }}
                        </script>
                    </div>
                    
                </div>
            </div>
        </div>
    </body></html>
    """)


#@admin_bp.route("/", methods=["GET", "POST"])
#def admin_console():
#    # 💡 1. 嚴格鎖定頂部按鈕 Session
#    current_db_key = session.get("current_opus_db", "intelligence")
#    if current_db_key not in DB_MAP: 
#        current_db_key = "intelligence"
#        
#    current_db_path = DB_MAP[current_db_key]["path"]
#    
#    # 讀取當前資料表清單
#    tables_query = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
#    tables_res, _, _ = query_db(current_db_path, tables_query)
#    table_list = [row["name"] for row in tables_res] if tables_res else []
#
#    # 狀態與頁籤追蹤紀錄
#    active_table = request.args.get("table", "").strip()
#    current_tab = request.args.get("tab", request.form.get("tab", "1")).strip()
#
#    # 💡 智慧首表自動對齊引擎
#    if not active_table and table_list:
#        active_table = table_list[0]
#
#    # 安全防禦：防範跨庫殘留異常
#    if active_table and active_table not in table_list:
#        active_table = table_list[0] if table_list else ""
#
#    edit_pk_val = request.args.get("edit_pk", "")
#    edit_schema_col = request.args.get("edit_schema_col", "")
#    
#    if edit_schema_col: current_tab = "1"
#    if edit_pk_val: current_tab = "2"
#
#    # 優先拿表單送出的 SQL，若沒有且點擊了 Table，則自動組裝預設 SELECT 查詢
#    sql_input = request.form.get("sql", "").strip()
#    if not sql_input and active_table:
#        sql_input = f"SELECT * FROM {active_table} LIMIT 50;"
#
#    # 如果是使用者點擊「執行 SQL 指令」送出表單（POST），後端強制鎖定在第 3 頁
#    if request.method == "POST" and request.form.get("sql"):
#        current_tab = "3"
#
#    query_results = None
#    column_names = []
#    sql_error = None
#    success_msg = session.pop("action_success", None)
#
#    # 驅動底層安全引擎執行 SQL 查詢
#    if sql_input and not sql_input.startswith("SELECT * FROM  LIMIT"):
#        res, desc, err = query_db(current_db_path, sql_input)
#        if err: 
#            sql_error = err
#        else:
#            query_results = res
#            # 💡 終極核心修正：d 是一個元組描述，必須精準取其第 0 項 d[0] 或者是當 d 本身是字串時取 d，
#            #      這樣 column_names 裡面儲存的才會是 100% 乾淨的純文字欄位名（如 'id'），徹底絕育所有異常！
#            if desc:
#                column_names = [str(d[0]) if isinstance(d, (tuple, list)) else str(d) for d in desc]
#    else:
#        sql_input = ""
#
#    # 在後端將第三頁籤的結果表格安全拼裝，將可能發生的 IndexError 阻斷在 Python 層
#    sql_tab_result_html = ""
#    if current_tab == "3" and sql_error:
#        sql_tab_result_html = f'<div class="alert alert-danger font-monospace small mt-2">❌ SQL 執行失敗: {sql_error}</div>'
#    elif current_tab == "3" and query_results is not None:
#        if isinstance(query_results, str):
#            sql_tab_result_html = f'<div class="alert alert-success small mt-3">✔️ {query_results}</div>'
#        elif len(query_results) == 0:
#            sql_tab_result_html = '<div class="alert alert-warning small mt-2">⚪ 查詢成功，但此語法沒有回傳任何數據列。</div>'
#        elif column_names:
#            try:
#                th_tags = "".join([f"<th>{c}</th>" for c in column_names])
#                tr_tags = ""
#                for r in query_results:
#                    row_keys = {str(k).lower(): k for k in r.keys()} if hasattr(r, 'keys') else {}
#                    td_tags = ""
#                    for c in column_names:
#                        target_key = row_keys.get(c.lower(), c)
#                        try: val = r[target_key]
#                        except: val = ""
#                        td_tags += f"<td>{str(val) if val is not None else ''}</td>"
#                    tr_tags += f"<tr>{td_tags}</tr>"
#                
#                sql_tab_result_html = f"""
#                <div class="table-responsive shadow-sm rounded border border-secondary mt-3" style="max-height: 300px; overflow-y: auto; overflow-x: auto;">
#                    <table class="table table-dark table-striped table-hover table-bordered small m-0">
#                        <thead class="table-secondary text-dark sticky-top"><tr>{th_tags}</tr></thead>
#                        <tbody>{tr_tags}</tbody>
#                    </table>
#                </div>"""
#            except Exception as e:
#                sql_tab_result_html = f'<div class="alert alert-danger small mt-2">❌ 前端渲染異常攔截: {str(e)}</div>'
#    # --- 🛠️ 區塊 A：資料表結構定義與穩定行內異動引擎 ---
#    schema_html = ""
#    pk_column = None
#    
#    if active_table:
#        pragma_sql = f"PRAGMA table_info({active_table});"
#        pragma_res, _, _ = query_db(current_db_path, pragma_sql)
#        
#        if pragma_res:
#            schema_rows = ""
#            for r in pragma_res:
#                try: r_name = r["name"]
#                except:
#                    try: r_name = r["NAME"]
#                    except: r_name = r
#                    
#                try: r_type = r["type"]
#                except:
#                    try: r_type = r["TYPE"]
#                    except: r_type = r
#                    
#                try: r_notnull = r["notnull"]
#                except:
#                    try: r_notnull = r["NOTNULL"]
#                    except: r_notnull = r
#                    
#                try: r_dflt = r["dflt_value"]
#                except:
#                    try: r_dflt = r["DFLT_VALUE"]
#                    except: r_dflt = r
#                    
#                try: r_pk = r["pk"]
#                except:
#                    try: r_pk = r["PK"]
#                    except: r_pk = r
#                
#                is_pk = "⭐ YES" if r_pk else "NO"
#                if r_pk: pk_column = r_name
#                
#                is_editing_this_col = (edit_schema_col and edit_schema_col == r_name)
#                
#                if is_editing_this_col:
#                    schema_rows += f"""
#                    <tr>
#                        <td><input type="text" name="n_name" value="{r_name}" class="form-control form-control-sm bg-dark text-white border-primary" form="schema_edit_form" required></td>
#                        <td>
#                            <select name="n_type" class="form-select form-select-sm bg-dark text-white border-primary" form="schema_edit_form">
#                                <option value="TEXT" {"selected" if r_type=='TEXT' else ""}>TEXT</option>
#                                <option value="INTEGER" {"selected" if r_type=='INTEGER' else ""}>INTEGER</option>
#                                <option value="REAL" {"selected" if r_type=='REAL' else ""}>REAL</option>
#                                <option value="BLOB" {"selected" if r_type=='BLOB' else ""}>BLOB</option>
#                            </select>
#                        </td>
#                        <td>
#                            <select name="n_notnull" class="form-select form-select-sm bg-dark text-white border-primary" form="schema_edit_form">
#                                <option value="0" {"selected" if not r_notnull else ""}>NULL</option>
#                                <option value="1" {"selected" if r_notnull else ""}>❌ NOT NULL</option>
#                            </select>
#                        </td>
#                        <td><input type="text" name="n_dflt" value="{r_dflt if r_dflt is not None else ''}" placeholder="無" class="form-control form-control-sm bg-dark text-white border-primary" form="schema_edit_form"></td>
#                        <td class="text-warning">{is_pk}</td>
#                        <td class="text-center">
#                            <button type="submit" form="schema_edit_form" class="btn btn-xs btn-primary fw-bold py-1 px-2 me-1">💾 儲存</button>
#                            <a href="/admin/?table={active_table}&tab=1" class="btn btn-xs btn-outline-secondary py-1 px-2">取消</a>
#                        </td>
#                    </tr>"""
#                else:
#                    schema_rows += f"""
#                    <tr>
#                        <td><code>{r_name}</code></td>
#                        <td><span class="badge bg-secondary">{r_type}</span></td>
#                        <td>{'❌ NOT NULL' if r_notnull else 'NULL'}</td>
#                        <td>{r_dflt if r_dflt is not None else '<span class="text-muted">None</span>'}</td>
#                        <td class="text-warning">{is_pk}</td>
#                        <td class="text-center">
#                            <a href="/admin/?table={active_table}&edit_schema_col={r_name}&tab=1" class="btn btn-xs btn-outline-warning py-0 px-2 fw-bold me-1">✏️ 編輯結構</a>
#                            <a href="/admin/schema/drop_col?table={active_table}&col={r_name}" 
#                               class="btn btn-xs btn-outline-danger py-0 px-2 fw-bold"
#                               onclick="return confirm('警告：確定要徹底刪除「{r_name}」欄位嗎？數據將無法恢復！');">❌ 刪除</a>
#                        </td>
#                    </tr>"""
#            
#            schema_html = f"""
#            <form id="schema_edit_form" method="POST" action="/admin/schema/edit_col_submit?table={active_table}&old_col={edit_schema_col}"></form>
#            <div class="d-flex justify-content-between align-items-center mb-3">
#                <h6 class="text-info fw-bold m-0">📋 資料表結構定義與異動：{active_table}</h6>
#                <form method="POST" action="/admin/schema/add_col?table={active_table}" class="row g-2 align-items-center m-0">
#                    <div class="col-auto"><input type="text" name="new_col_name" class="form-control form-control-sm bg-dark text-white border-secondary" placeholder="新欄位名稱" required></div>
#                    <div class="col-auto">
#                        <select name="new_col_type" class="form-select form-select-sm bg-dark text-white border-secondary">
#                            <option value="TEXT">TEXT (字串)</option>
#                            <option value="INTEGER">INTEGER (整數)</option>
#                            <option value="REAL">REAL (浮點數)</option>
#                            <option value="BLOB">BLOB (二進制)</option>
#                        </select>
#                    </div>
#                    <div class="col-auto"><button type="submit" class="btn btn-info btn-sm fw-bold">➕ 新增欄位</button></div>
#                </form>
#            </div>
#            <table class="table table-dark table-sm table-bordered m-0" style="font-size: 13px;">
#                <thead class="table-info text-dark"><tr><th>欄位名稱</th><th>資料型態</th><th>空值約束</th><th>預設值</th><th>主鍵判定</th><th class="text-center">結構異動管理</th></tr></thead>
#                <tbody>{schema_rows}</tbody>
#            </table>"""
#
#     # --- 📊 區塊 B：渲染數據內容與一鍵增刪改的數據視窗 ---
#    results_table_html = ""
#    if sql_error:
#        if current_tab == "2":
#            results_table_html = f'<div class="alert alert-danger font-monospace small">❌ SQL 錯誤: {sql_error}</div>'
#    elif query_results is not None:
#        if isinstance(query_results, str):
#            results_table_html = f'<div class="alert alert-success small">✔️ {query_results}</div>'
#        elif len(query_results) == 0:
#            results_table_html = '<div class="alert alert-warning small">⚪ 查詢成功，但目前沒有任何數據。</div>'
#        else:
#            # 1. 新增數據的 Input 表單（橫向流式排版維持不變）
#            insert_form_html = ""
#            if active_table and pk_column:
#                fields_inputs = "".join([
#                    f"""
#                    <div style="display: flex; flex-direction: column; min-width: 110px; flex: 1;">
#                        <label class="text-muted fw-bold mb-1" style="font-size: 11px;">{col}</label>
#                        <input type="text" name="val_{col}" class="form-control form-control-sm bg-dark text-white" 
#                               style="border: 1px solid #45475a;"
#                               {"placeholder='(自增主鍵)' disabled" if col==pk_column else ""}>
#                    </div>
#                    """ 
#                    for col in column_names
#                ])
#                insert_form_html = f"""
#                <div class="p-3 mb-4 rounded shadow-sm" style="background-color: #11111b; border: 1px solid #a6e3a1;">
#                    <div class="d-flex justify-content-between align-items-center mb-3">
#                        <h6 class="text-success fw-bold m-0" style="font-size: 13px;">➕ 快速追加新數據至 {active_table}</h6>
#                        <button type="submit" form="master_insert_form" class="btn btn-success btn-sm fw-bold px-4 shadow">⚡ 送出新增</button>
#                    </div>
#                    <form id="master_insert_form" method="POST" action="/admin/insert?table={active_table}">
#                        <div style="display: flex; flex-direction: row; flex-wrap: wrap; gap: 12px; align-items: flex-end;">
#                            {fields_inputs}
#                        </div>
#                    </form>
#                </div>"""
#                
#            thead = "".join([f'<th style="min-width: 110px; {"min-width: 350px;" if col=="summary" else ""} text-align: left; padding: 10px;">{col}</th>' for col in column_names]) + ( '<th style="width: 130px; min-width: 130px; text-align: center; position: sticky; right: 0; background: #343a40 !important; color: #fff; z-index: 15; box-shadow: -2px 0 5px rgba(0,0,0,0.3);">數據異動項目</th>' if pk_column else "" )
#            
#            tbody = ""
#            modal_overlay_html = "" # 💡 新增：用來存放彈出視窗的 HTML 容器
#            
#            for row in query_results:
#                row_keys_map = {str(k).lower(): k for k in row.keys()} if hasattr(row, 'keys') else {}
#                pk_target_key = row_keys_map.get(str(pk_column).lower(), pk_column) if pk_column else None
#                try: pk_val = str(row[pk_target_key]) if pk_target_key else None
#                except: pk_val = None
#                
#                is_editing_this_row = (pk_val and edit_pk_val and pk_val == str(edit_pk_val))
#
#                # 🟢 核心優化：表格回歸 100% 純瀏覽乾淨骨架，不論是不是修改狀態，表格欄位絕不動彈、絕不破裂！
#                tbody += "<tr>"
#                for col in column_names:
#                    curr_key = row_keys_map.get(col.lower(), col)
#                    try: val_data = str(row[curr_key]) if row[curr_key] is not None else ""
#                    except: val_data = ""
#                    
#                    if col == "summary":
#                        tbody += f'<td style="white-space: normal; word-break: break-all; min-width: 350px; text-align: justify; padding: 8px;">{val_data}</td>'
#                    else:
#                        tbody += f'<td style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 8px 12px; text-align: center;">{val_data}</td>'
#                
#                if pk_column and pk_column in column_names:
#                    tbody += f"""
#                    <td class="text-center" style="position: sticky; right: 0; background: #181825; z-index: 12; border-left: 2px solid #313244 !important; white-space: nowrap; padding: 8px; box-shadow: -3px 0 6px rgba(0,0,0,0.4);">
#                        <!-- 💡 點擊編輯直接物理跳轉至錨點 #modal-{pk_val} 浮起遮罩視窗 -->
#                        <a href="#modal-{pk_val}" class="btn btn-xs btn-outline-warning py-1 px-2 fw-bold me-1">✏️ 編輯</a>
#                        <a href="/admin/delete?table={active_table}&pk_col={pk_column}&pk_val={pk_val}" 
#                           class="btn btn-xs btn-outline-danger py-1 px-2 fw-bold" 
#                           onclick="return confirm('確定要刪除主鍵為 {pk_val} 的紀錄嗎？');">❌ 刪除</a>
#                    </td>"""
#                tbody += "</tr>"
#
#                # 💡 核心黑科技：在迴圈內為「每一筆資料」同步組裝垂直排列的獨立彈出遮罩視窗 (Modal)
#                if pk_column and pk_column in column_names:
#                    modal_inputs = ""
#                    for col in column_names:
#                        curr_key = row_keys_map.get(col.lower(), col)
#                        try: val_data = str(row[curr_key]) if row[curr_key] is not None else ""
#                        except: val_data = ""
#                        
#                        if col == pk_column:
#                            modal_inputs += f'<div class="mb-3"><label class="form-label text-muted fw-bold small">{col} (主鍵)</label><input type="text" name="val_{col}" value="{val_data}" class="form-control form-control-sm bg-secondary text-dark" readonly></div>'
#                        elif col == "summary":
#                            modal_inputs += f'<div class="mb-3"><label class="form-label text-info fw-bold small">{col}</label><textarea name="val_{col}" class="form-control bg-dark text-white border-secondary" rows="4">{val_data}</textarea></div>'
#                        else:
#                            modal_inputs += f'<div class="mb-3" style="width: calc(50% - 6px);"><label class="form-label text-white small">{col}</label><input type="text" name="val_{col}" value="{val_data}" class="form-control form-control-sm bg-dark text-white border-secondary"></div>'
#                    
#                    modal_overlay_html += f"""
#                    <div id="modal-{pk_val}" class="custom-modal-backdrop">
#                        <div class="custom-modal-card p-4 rounded-3 shadow-lg card-editor">
#                            <div class="d-flex justify-content-between align-items-center mb-3 border-bottom border-secondary pb-2">
#                                <h5 class="text-warning fw-bold m-0" style="font-size:16px;">✏️ 編輯數據資料項目 (主鍵: {pk_val})</h5>
#                                <a href="#consoleTab" class="btn-close btn-close-white text-decoration-none"></a>
#                            </div>
#                            <form method="POST" action="/admin/update?table={active_table}&pk_col={pk_column}&pk_val={pk_val}">
#                                <div style="display: flex; flex-direction: row; flex-wrap: wrap; gap: 12px;">
#                                    {modal_inputs}
#                                </div>
#                                <div class="text-end border-top border-secondary pt-3 mt-2">
#                                    <a href="#consoleTab" class="btn btn-sm btn-outline-secondary me-2 px-3">取消</a>
#                                    <button type="submit" class="btn btn-sm btn-primary fw-bold px-4 shadow">💾 儲存修改</button>
#                                </div>
#                            </form>
#                        </div>
#                    </div>"""
#            
#            # 組裝完整的結果表格 HTML
#            results_table_html = f"""
#            {insert_form_html}
#            <div class="table-responsive shadow-sm rounded border border-secondary" style="max-height: 550px; overflow-y: auto; overflow-x: auto; white-space: nowrap;">
#                <table class="table table-dark table-striped table-hover table-bordered small m-0" style="table-layout: auto; width: max-content; min-width: 100%;">
#                    <thead class="table-secondary text-dark sticky-top" style="z-index: 16;"><tr>{thead}</tr></thead>
#                    <tbody>{tbody}</tbody>
#                </table>
#            </div>
#            <!-- 💡 注入所有資料列的物理遮罩隱藏盒子 -->
#            {modal_overlay_html}"""
#    # 💡 狀態樣式與活性高亮文字外提：完全杜絕 HTML 大括號引號衝突 Bug
#    tab1_display = "block" if current_tab == "1" else "none"
#    tab2_display = "block" if current_tab == "2" else "none"
#    tab3_display = "block" if current_tab == "3" else "none"
#    
#    tab1_active = "active" if current_tab == "1" else ""
#    tab2_active = "active" if current_tab == "2" else ""
#    tab3_active = "active" if current_tab == "3" else ""
#
#    return render_template_string(f"""
#    <!DOCTYPE html><html><head><title>交易系統核心主控台</title>
#    <link href="https://cloudflare.com" rel="stylesheet">
#    <style>
#        body {{ background-color: #1e1e2e; color: #cdd6f4; font-family: sans-serif; height: 100vh; display: flex; flex-direction: column; margin: 0; padding: 0; overflow: hidden; }}
#        .header-bar {{ background-color: #11111b; border-bottom: 2px solid #313244; padding: 15px 30px; flex-shrink: 0; }}
#        .workspace {{ display: flex; flex-direction: row; flex-grow: 1; height: calc(100vh - 82px); overflow: hidden; }}
#        .sidebar {{ background-color: #11111b; border-right: 2px solid #313244; width: 280px; flex-shrink: 0; overflow-y: auto; padding: 20px; }}
#        .main-content {{ flex-grow: 1; overflow-y: auto; padding: 25px; background-color: #1e1e2e; position: relative; }}
#        .card-editor {{ background-color: #181825; border: 1px solid #313244; }}
#        textarea {{ font-family: monospace; background-color: #1e1e2e !important; color: #a6e3a1 !important; border: 1px solid #45475a !important; }}
#        .active-table {{ background-color: #313244 !important; border-color: #a6e3a1 !important; }}
#        .btn-xs {{ font-size: 11px; padding: 2px 6px; }}
#        
#        .table-responsive::-webkit-scrollbar {{ height: 10px; width: 10px; }}
#        .table-responsive::-webkit-scrollbar-track {{ background: #11111b; }}
#        .table-responsive::-webkit-scrollbar-thumb {{ background: #45475a; border-radius: 5px; }}
#        .table-responsive::-webkit-scrollbar-thumb:hover {{ background: #585b70; }}
#
#        /* 橫向一字排開 Chrome 級分頁標籤 */
#        .chrome-tabs {{ border-bottom: 2px solid #313244 !important; gap: 6px; width: 100%; display: flex !important; flex-direction: row !important; list-style-type: none !important; padding-left: 0 !important; margin-bottom: 24px !important; }}
#        .chrome-item {{ list-style-type: none !important; margin: 0 !important; padding: 0 !important; }}
#        .chrome-link {{ background: none; color: #89b4fa; border: 1px solid #313244; border-bottom: none; font-weight: bold; padding: 10px 20px; border-top-left-radius: 6px; border-top-right-radius: 6px; cursor: pointer; display: block; text-decoration: none; transition: all 0.1s ease-in-out; user-select: none; }}
#        .chrome-link:hover {{ background-color: #313244; color: #f5e0dc; }}
#        .chrome-link.active {{ background-color: #181825 !important; color: #a6e3a1 !important; border-color: #313244 #313244 #181825 !important; box-shadow: 0 -2px 5px rgba(0,0,0,0.2); }}
#        
#        .custom-tab-panel {{ display: none; }}
#
#        /* 💡 核心黑科技：純 CSS 物理彈出遮罩視窗 (Modal) 引擎樣式 */
#        .custom-modal-backdrop {{
#            position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
#            background-color: rgba(0, 0, 0, 0.7); backdrop-filter: blur(4px);
#            z-index: 9999; display: none; align-items: center; justify-content: center;
#        }}
#        /* 當網址列錨點的 ID 與 Modal 的 ID 一致時，自動將其浮現顯示 */
#        .custom-modal-backdrop:target {{
#            display: flex !important;
#        }}
#        .custom-modal-card {{
#            width: 650px; max-width: 90%; max-height: 85vh; overflow-y: auto;
#            border: 2px solid #f9e2af !important; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
#        }}
#    </style>
#    </head><body>
#        <div class="header-bar d-flex justify-content-between align-items-center shadow">
#            <h4 class="fw-bold m-0 text-white">⚔️ 交易系統核心多資料庫戰情室</h4>
#            <div>{buttons_html}</div>
#        </div>
#        <div class="workspace">
#            <div class="sidebar">
#                <h5 class="text-white fw-bold mb-3 pb-2 border-bottom border-secondary" style="font-size:16px;">📂 結構資料表 ({len(table_list)})</h5>
#                <div class="list-group rounded shadow-sm w-100">{tables_html}</div>
#            </div>
#            <div class="main-content">
#                {f'<div class="alert alert-success p-2 small">✔️ {success_msg}</div>' if success_msg else ''}
#                
#                <ul class="chrome-tabs" id="consoleTab">
#                    <li class="chrome-item">
#                        <a href="/admin/?table={active_table}&tab=1" class="chrome-link {tab1_active}">📋 (1) 表結構定義與異動</a>
#                    </li>
#                    <li class="chrome-item">
#                        <a href="/admin/?table={active_table}&tab=2" class="chrome-link {tab2_active}">📊 (2) 數據視窗 & 新增單筆</a>
#                    </li>
#                    <li class="chrome-item">
#                        <a href="/admin/?table={active_table}&tab=3" class="chrome-link {tab3_active}">📝 (3) SQL 編輯與控制區</a>
#                    </li>
#                </ul>
#
#                <div class="tab-content" id="consoleTabContent">
#                    
#                    <!-- 📋 (1) 表結構定義與異動 面板 -->
#                    <div style="display: {tab1_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
#                        {schema_html if schema_html else '<div class="text-muted small py-3">⚪ 無可用的資料表結構。</div>'}
#                    </div>
#                    
#                    <!-- 📊 (2) 數據視窗 & 新增單筆 面板 -->
#                    <div style="display: {tab2_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
#                        {results_table_html if results_table_html else '<div class="text-muted small py-3">⚪ 無可用的加載數據。</div>'}
#                    </div>
#                    
#                    <!-- 📝 (3) SQL 編輯與控制區 面板 -->
#                    <div style="display: {tab3_display};" class="custom-tab-panel card card-editor p-4 rounded-3 shadow">
#                        <form method="POST" action="/admin/?table={active_table}">
#                            <input type="hidden" name="db" value="{current_db_key}">
#                            <input type="hidden" name="tab" value="3">
#                            <div class="d-flex justify-content-between align-items-center mb-3">
#                                <h5 class="text-success m-0 fw-bold">📝 全域 SQL 指令編譯器</h5>
#                                <span class="badge bg-danger font-monospace">ACTIVE: {current_db_key}.db</span>
#                            </div>
#                            <div class="mb-3">
#                                <textarea id="sql_editor" name="sql" class="form-control" rows="5">{sql_input}</textarea>
#                            </div>
#                            <div class="text-end mb-3">
#                                <button type="submit" class="btn btn-primary fw-bold px-5 shadow">⚡ 執行 SQL 指令</button>
#                            </div>
#                        </form>
#                        
#                        {sql_tab_result_html}
#                    </div>
#                    
#                </div>
#            </div>
#        </div>
#    </body></html>
#    """)
#
    

    

@admin_bp.route("/insert", methods=["POST"])
def db_insert():
    table = request.args.get("table")
    current_db_key = session.get("current_opus_db", "intelligence")
    db_path = DB_MAP[current_db_key]["path"]
    
    pragma_res, _, _ = query_db(db_path, f"PRAGMA table_info({table});")
    if pragma_res and table:
        cols = []
        vals = []
        placeholders = []
        for r in pragma_res:
            val = request.form.get(f"val_{r['name']}", "").strip()
            # 💡 終極防呆：不論是自增主鍵還是 disabled 欄位，只要為空或未傳入，就安全跳過交給 SQLite 生成
            if r['pk'] and (not val or val.lower() == "none" or "(自增主鍵)" in val):
                continue
            cols.append(r['name'])
            vals.append(val)
            placeholders.append("?")
            
        if cols:
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)});"
            _, _, err = query_db(db_path, sql, vals)
            session["action_success"] = f"新增資料失敗: {err}" if err else "恭喜！新交易預報數據已成功寫入資料庫！"
        else:
            session["action_success"] = "新增失敗：未接收到有效的資料欄位參數。"
        
    return redirect(f"/admin/?table={table}")
    
#@admin_bp.route("/insert", methods=["POST"])
#def db_insert():
#    table = request.args.get("table")
#    current_db_key = session.get("current_opus_db", "intelligence")
#    db_path = DB_MAP[current_db_key]["path"]
#    
#    # 自動撈取表內欄位定義，進行安全的結構比對過濾
#    pragma_res, _, _ = query_db(db_path, f"PRAGMA table_info({table});")
#    if pragma_res and table:
#        cols = []
#        vals = []
#        placeholders = []
#        for r in pragma_res:
#            val = request.form.get(f"val_{r['name']}", "").strip()
#            # 若為主鍵且使用者未輸入，跳過該欄位交由 SQLite 自動生成 (如 AUTOINCREMENT)
#            if r['pk'] and not val:
#                continue
#            cols.append(r['name'])
#            vals.append(val)
#            placeholders.append("?")
#            
#        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(placeholders)});"
#        _, _, err = query_db(db_path, sql, vals)
#        session["action_success"] = f"新增失敗: {err}" if err else "單筆數據新增成功！"
#        
#    return redirect(f"/admin/?table={table}")

@admin_bp.route("/update", methods=["POST"])
def db_update():
    table = request.args.get("table")
    pk_col = request.args.get("pk_col")
    pk_val = request.args.get("pk_val")
    current_db_key = session.get("current_opus_db", "intelligence")
    db_path = DB_MAP[current_db_key]["path"]
    
    pragma_res, _, _ = query_db(db_path, f"PRAGMA table_info({table});")
    if pragma_res and table and pk_col and pk_val:
        set_clauses = []
        vals = []
        for r in pragma_res:
            if r['name'] != pk_col:
                val = request.form.get(f"val_{r['name']}")
                set_clauses.append(f"{r['name']} = ?")
                vals.append(val)
        
        vals.append(pk_val)
        sql = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {pk_col} = ?;"
        _, _, err = query_db(db_path, sql, vals)
        session["action_success"] = f"修改失敗: {err}" if err else "數據修改成功並已儲存！"
        
    return redirect(f"/admin/?table={table}")

@admin_bp.route("/delete")
def db_delete():
    table = request.args.get("table")
    pk_col = request.args.get("pk_col")
    pk_val = request.args.get("pk_val")
    current_db_key = session.get("current_opus_db", "intelligence")
    
    if table and pk_col and pk_val:
        db_path = DB_MAP[current_db_key]["path"]
        sql = f"DELETE FROM {table} WHERE {pk_col} = ?;"
        _, _, err = query_db(db_path, sql, (pk_val,))
        session["action_success"] = f"刪除失敗: {err}" if err else "數據已徹底移出資料庫！"
        
    return redirect(f"/admin/?table={table}")

# --- ⚙️ 區態結構修改路由 (Schema ALTER TABLE APIs) ---------------------------

@admin_bp.route("/schema/add_col", methods=["POST"])
def schema_add_column():
    table = request.args.get("table")
    new_name = request.form.get("new_col_name", "").strip()
    new_type = request.form.get("new_col_type", "TEXT")
    current_db_key = session.get("current_opus_db", "intelligence")
    
    if table and new_name:
        db_path = DB_MAP[current_db_key]["path"]
        add_sql = f"ALTER TABLE {table} ADD COLUMN {new_name} {new_type};"
        _, _, err = query_db(db_path, add_sql)
        session["action_success"] = f"欄位新增失敗: {err}" if err else f"成功為 {table} 資料表新增欄位「{new_name}」({new_type})！"
    return redirect(f"/admin/?table={table}")

@admin_bp.route("/schema/drop_col")
def schema_drop_column():
    table = request.args.get("table")
    col = request.args.get("col")
    current_db_key = session.get("current_opus_db", "intelligence")
    
    if table and col:
        db_path = DB_MAP[current_db_key]["path"]
        drop_sql = f"ALTER TABLE {table} DROP COLUMN {col};"
        _, _, err = query_db(db_path, drop_sql)
        session["action_success"] = f"刪除欄位失敗 (可能因 SQLite 版本限制或外鍵約束): {err}" if err else f"成功從 {table} 徹底刪除欄位「{col}」！"
    return redirect(f"/admin/?table={table}")

# --- 8. 資料庫路由切換 --------------------------------------------------------

@admin_bp.route("/switch/<db_name>")
def switch_database_session(db_name):
    if db_name in DB_MAP:
        session["current_opus_db"] = db_name
    return redirect("/admin/")

def init_admin_web_ui(app):
    app.register_blueprint(admin_bp)
