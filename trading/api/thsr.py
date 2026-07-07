"""
trading/api/thsr.py — 高鐵訂票 API 修正版
修正重點：強化錯誤處理，確保路由與前端對接正確
"""
from flask import Blueprint, g, jsonify, request
from thsr_ticket.remote.http_request import HTTPRequest
from thsr_ticket.model.web.booking_form.booking_form import BookingForm
from thsr_ticket.model.web.confirm_train import ConfirmTrain
from thsr_ticket.model.web.confirm_ticket import ConfirmTicket
from thsr_ticket.view_model.avail_trains import AvailTrains
from thsr_ticket.view_model.error_feedback import ErrorFeedback
from thsr_ticket.view_model.booking_result import BookingResult

from trading.api.auth import require_auth
from trading.services.thsr_session import thsr_session_manager

thsr_bp = Blueprint("thsr", __name__)

def _uid() -> str:
    return str(getattr(g, "current_user_id", None) or "default")

def _errors_or_none(html: bytes):
    errors = ErrorFeedback().parse(html)
    return [e.msg for e in errors] if errors else None



# ── 靜態資料：站名、時刻表選項、票種 ────────────────────────────

@thsr_bp.route("/api/thsr/stations", methods=["GET"])
@require_auth
def stations():
    return jsonify({
        "ok": True,
        "stations": [{"id": s.value, "name": s.name} for s in StationMapping],
        "time_table": [{"value": t.value, "time": t.time} for t in TimeTable()],
        "class_type": [{"value": 0, "label": "標準車廂"}, {"value": 1, "label": "商務車廂"}],
        "seat_prefer": [
            {"value": "radio17", "label": "無偏好"},
            {"value": "radio19", "label": "靠窗"},
            {"value": "radio21", "label": "靠走道"},
        ],
    })


@thsr_bp.route("/select-train", methods=["POST"])
@require_auth
def select_train():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    index = data.get("index")
    
    sess = thsr_session_manager.get(session_id, _uid())
    if not sess:
        return jsonify({"ok": False, "error": "Session 已失效，請重新查詢"}), 404
    
    if not sess.avail_trains:
        return jsonify({"ok": False, "error": "無可用車次資料，請重新執行查詢"}), 400
    
    try:
        # 索引校正
        idx = int(index) - 1
        if idx < 0 or idx >= len(sess.avail_trains):
            return jsonify({"ok": False, "error": "無效的車次選擇"}), 400
        train = sess.avail_trains[idx]
    except Exception as e:
        return jsonify({"ok": False, "error": f"處理車次選擇發生錯誤: {str(e)}"}), 400

    confirm_train = ConfirmTrain()
    confirm_train.selection = train.form_value
    try:
        result = sess.client.submit_train(confirm_train.get_params())
        errors = _errors_or_none(result.content)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        
        sess.confirm_train = confirm_train
        sess.confirm_ticket = ConfirmTicket()
        sess.state = "awaiting_personal_info"
        return jsonify({"ok": True, "next": "personal_info"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"與高鐵系統連線失敗: {str(e)}"}), 502

@thsr_bp.route("/confirm", methods=["POST"])
@require_auth
def confirm():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    personal_id = data.get("personal_id", "")
    phone = data.get("phone", "")
    
    sess = thsr_session_manager.get(session_id, _uid())
    if not sess or not sess.confirm_ticket:
        return jsonify({"ok": False, "error": "Session 已過期，請重新開始訂票流程"}), 404

    try:
        sess.confirm_ticket.personal_id = personal_id
        sess.confirm_ticket.phone = phone
        result = sess.client.submit_ticket(sess.confirm_ticket.get_params())
    except Exception as e:
        return jsonify({"ok": False, "error": f"送出訂票確認失敗: {str(e)}"}), 502

    errors = _errors_or_none(result.content)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    try:
        tickets = BookingResult().parse(result.content)
        ticket = tickets[0]
    except Exception as e:
        return jsonify({"ok": False, "error": "無法解析訂票結果，請至高鐵官網確認訂位"}), 502

    sess.state = "done"
    thsr_session_manager.delete(session_id)

    return jsonify({
        "ok": True,
        "ticket": {
            "booking_id": ticket.id,
            "payment_deadline": ticket.payment_deadline,
            "seat_class": ticket.seat_class,
            "ticket_num_info": ticket.ticket_num_info,
            "start_station": ticket.start_station,
            "dest_station": ticket.dest_station,
            "train_id": ticket.train_id,
            "depart_time": ticket.depart_time,
            "arrival_time": ticket.arrival_time,
            "date": ticket.date,
            "seat": ticket.seat,
            "price": ticket.price
        },
        "message": "訂票成功！"
    })