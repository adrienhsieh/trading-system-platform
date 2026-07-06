@search_bp.route("/api/search")
def search():
    query = request.args.get("q", "").upper() # 是否有做轉大寫？
    # 檢查這裡是如何過濾的
    results = [k for k in all_keywords if query in k.upper()] 
    return jsonify(results)