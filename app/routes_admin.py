"""Studio-admin only: unlock masters, set prices, answer negotiations, reassign editors, publish links."""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import clean_http_url, endpoint, parse_body
from .db import dumps, load_rate_card, loads, transaction
from .errors import ApiError
from .routes_orders import _order_id, add_message, get_order, order_json, touch
from .schemas import DecisionIn, LinksIn, PricingIn, ReassignIn, UnlockIn
from .serializers import inr, num


@endpoint("ADMIN")
async def unlock(request, conn, principal):
    settings = request.app.state.settings
    order = get_order(conn, principal, _order_id(request))
    data = await parse_body(request, UnlockIn)
    with transaction(conn):
        conn.execute("UPDATE orders SET unlocked = ?, status = ? WHERE id = ?", (
            1 if data.unlocked else 0,
            "COMPLETED & UNLOCKED" if data.unlocked else "IN PRODUCTION", order["id"]))
        if data.unlocked and order["payment_json"]:
            proof = loads(order["payment_json"], {})
            proof["status"] = "APPROVED"
            conn.execute("UPDATE orders SET payment_json = ? WHERE id = ?", (dumps(proof), order["id"]))
        add_message(conn, settings, order["id"], "system",
                    "Studio Staff verified payment reference! Watermark removed and 4K clean master unlocked."
                    if data.unlocked else "Project master reset to draft preview mode by staff.")
        touch(conn, order["id"])
    return order_json(conn, settings, principal, order["id"])


@endpoint("ADMIN")
async def set_pricing(request, conn, principal):
    settings = request.app.state.settings
    order = get_order(conn, principal, _order_id(request))
    data = await parse_body(request, PricingIn)
    price, payout = round(data.price, 2), round(data.editorPayout, 2)
    negotiation = loads(order["negotiation_json"])
    if negotiation:
        negotiation["status"] = "ADMIN_APPROVED"
    with transaction(conn):
        conn.execute("UPDATE orders SET price = ?, editor_payout = ?, negotiation_json = ? WHERE id = ?",
                     (price, payout, dumps(negotiation) if negotiation else None, order["id"]))
        add_message(conn, settings, order["id"], "system",
                    f"Studio Admin updated pricing: Final Client Fee set to ${num(price)} USD "
                    f"(₹{inr(settings, price)} INR). Editor Payout set to ${num(payout)} USD.", "private")
        touch(conn, order["id"])
    return order_json(conn, settings, principal, order["id"])


@endpoint("ADMIN")
async def decide_negotiation(request, conn, principal):
    settings = request.app.state.settings
    order = get_order(conn, principal, _order_id(request))
    data = await parse_body(request, DecisionIn)
    negotiation = loads(order["negotiation_json"])
    if not negotiation or negotiation.get("status") != "PENDING_ADMIN_REVIEW":
        raise ApiError(409, "There is no pending price offer on this order.")
    with transaction(conn):
        if data.decision == "accept":
            price = float(negotiation["proposedPrice"])
            rate = next((r for r in load_rate_card(conn) if r["type"] == order["project_type"]), None)
            payout = float(rate["editorPayoutDefault"]) if rate else round(price * 0.45, 2)
            negotiation["status"] = "ACCEPTED_BY_ADMIN"
            conn.execute("UPDATE orders SET price = ?, editor_payout = ?, negotiation_json = ? WHERE id = ?",
                         (price, payout, dumps(negotiation), order["id"]))
            add_message(conn, settings, order["id"], "system",
                        f"Studio Admin ACCEPTED your price negotiation offer! Price adjusted to "
                        f"${num(price)} USD (₹{inr(settings, price)} INR).", "private")
        else:
            negotiation["status"] = "DECLINED_BY_ADMIN"
            conn.execute("UPDATE orders SET negotiation_json = ? WHERE id = ?", (dumps(negotiation), order["id"]))
            add_message(conn, settings, order["id"], "system",
                        f"Studio Admin reviewed your price counter-offer. The standard rate of "
                        f"${num(order['price'])} USD remains active. You can discuss details in project chat.", "private")
        touch(conn, order["id"])
    return order_json(conn, settings, principal, order["id"])


@endpoint("ADMIN")
async def reassign(request, conn, principal):
    settings = request.app.state.settings
    order = get_order(conn, principal, _order_id(request))
    data = await parse_body(request, ReassignIn)
    editor = conn.execute("SELECT * FROM editors WHERE id = ? AND active = 1", (data.editorId,)).fetchone()
    if editor is None:
        raise ApiError(422, "That editor is not available.")
    with transaction(conn):
        conn.execute("UPDATE orders SET editor_id = ? WHERE id = ?", (editor["id"], order["id"]))
        add_message(conn, settings, order["id"], "system",
                    f"Project reassigned by Studio Admin to editor: {editor['name']}")
        touch(conn, order["id"])
    return order_json(conn, settings, principal, order["id"])


@endpoint("ADMIN")
async def set_links(request, conn, principal):
    settings = request.app.state.settings
    order = get_order(conn, principal, _order_id(request))
    data = await parse_body(request, LinksIn)
    draft = clean_http_url(data.draftUrl) if data.draftUrl else order["draft_url"]
    clean = clean_http_url(data.cleanUrl) if data.cleanUrl else order["clean_url"]
    with transaction(conn):
        conn.execute("UPDATE orders SET draft_url = ?, clean_url = ? WHERE id = ?", (draft, clean, order["id"]))
        add_message(conn, settings, order["id"], "system", "New 4K Video Render exports published by studio staff.")
        touch(conn, order["id"])
    return order_json(conn, settings, principal, order["id"])


@endpoint("ADMIN")
async def list_inquiries(request, conn, principal):
    rows = conn.execute("SELECT id,name,email,phone,created_at FROM inquiries ORDER BY id DESC LIMIT 500").fetchall()
    return JSONResponse({"inquiries": [dict(r) for r in rows]})


routes = [
    Route("/api/admin/orders/{order_id}/unlock", unlock, methods=["POST"]),
    Route("/api/admin/orders/{order_id}/pricing", set_pricing, methods=["POST"]),
    Route("/api/admin/orders/{order_id}/negotiation", decide_negotiation, methods=["POST"]),
    Route("/api/admin/orders/{order_id}/reassign", reassign, methods=["POST"]),
    Route("/api/admin/orders/{order_id}/links", set_links, methods=["PUT"]),
    Route("/api/admin/inquiries", list_inquiries, methods=["GET"]),
]
