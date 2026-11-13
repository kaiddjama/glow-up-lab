#!/usr/bin/env python3
"""E-mail « commande en préparation » à la cliente, quand Hoodo marque une commande PAYÉE puis « En cours ».

  python3 -I order_notify.py list       lists the orders that would get the e-mail (also to $GITHUB_OUTPUT: count)
  python3 -I order_notify.py baseline   tags every order that qualifies right now "prepa-notifiee" WITHOUT sending anything
                                        (run once before switching the sending on: clients already served get nothing)
  python3 -I order_notify.py send       sends the e-mail, one per order, then the order keeps the tag prepa-notifiee

An order qualifies when: created in the last WINDOW_DAYS days, not cancelled, financial status PAID (a pending Waafi / CAC Pay
payment never qualifies), fulfillment status IN_PROGRESS, no tag prepa-notifiee, no tag prepa-ignoree (put it on an order to
skip it), a valid e-mail. The tag is written BEFORE the e-mail leaves, so an order can never get two (if the sending fails the
tag is taken off again and the next run tries again).

Sending is OFF unless ALL of these hold: ORDER_NOTIFY_ENABLED=1 (repository variable) and SMTP_USER + SMTP_PASSWORD (secrets).
Otherwise `send` only reports what it would do. DRY_RUN=1 also reports only. At most MAX_PER_RUN e-mails per run.
Needs the app scopes read_orders and write_orders. SMTP_HOST (default smtp.zoho.com), SMTP_PORT (default 465, SSL).
The text is the one shown to and approved by the owner: notifications/messages-commande-2026-11-13.md (project files).
"""
import datetime as dt
import html
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python -I does not add the script folder
import amazon_sync as s  # noqa: E402

WINDOW_DAYS = 7
MAX_PER_RUN = 5
TAG = "prepa-notifiee"
SKIP_TAG = "prepa-ignoree"
SENDER_NAME = "Aimé Essentials"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Q = """query($q:String!,$after:String){ orders(first:50, after:$after, query:$q, sortKey:CREATED_AT){
  pageInfo{hasNextPage endCursor}
  nodes{ id name createdAt tags email cancelledAt displayFinancialStatus displayFulfillmentStatus
    shippingAddress{ firstName } billingAddress{ firstName } } } }"""
TAGS_ADD_M = """mutation($id:ID!,$t:[String!]!){tagsAdd(id:$id, tags:$t){userErrors{field message}}}"""
TAGS_REMOVE_M = """mutation($id:ID!,$t:[String!]!){tagsRemove(id:$id, tags:$t){userErrors{field message}}}"""


def qualifying_orders():
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = f"created_at:>={since} financial_status:paid -tag:{TAG} -tag:{SKIP_TAG} -status:cancelled"
    found, after = [], None
    while True:
        data = s.gql(Q, {"q": q, "after": after})["orders"]
        for o in data["nodes"]:
            if o["cancelledAt"] or o["displayFinancialStatus"] != "PAID" or o["displayFulfillmentStatus"] != "IN_PROGRESS":
                continue  # re-checked here: the search filter alone is never trusted for a message to a client
            if TAG in o["tags"] or SKIP_TAG in o["tags"]:
                continue
            found.append(o)
        if not data["pageInfo"]["hasNextPage"]:
            return found
        after = data["pageInfo"]["endCursor"]


def first_name(o):
    for k in ("shippingAddress", "billingAddress"):
        n = ((o.get(k) or {}).get("firstName") or "").strip()
        if n:
            return n
    return ""


def build_message(o, to):
    name, number = first_name(o), o["name"]
    hello = f"Bonjour {name}," if name else "Bonjour,"
    lines = [
        hello,
        "",
        f"Merci, nous avons bien reçu votre paiement. Votre commande {number} est maintenant en préparation chez Aimé Essentials.",
        "",
        "Nous réunissons vos produits et organisons leur acheminement vers Djibouti. Comptez 4 à 5 jours pour la livraison.",
        "",
        "Vous recevrez un nouvel e-mail dès que votre commande sera en route.",
        "",
        "Une question ? Répondez à cet e-mail ou écrivez-nous sur WhatsApp au +253 77 22 37 37.",
        "",
        "À très vite,",
        "L'équipe Aimé Essentials",
    ]
    text = "\n".join(lines)
    paras = "".join(f"<p style=\"margin:0 0 14px\">{html.escape(x)}</p>" for x in
                    [hello, lines[2], lines[4], lines[6], lines[8]]) + \
        f"<p style=\"margin:0\">{html.escape(lines[10])}<br>{html.escape(lines[11])}</p>"
    page = ("<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px\">"
            + paras + "</div>")
    msg = EmailMessage()
    user = os.environ["SMTP_USER"]
    msg["Subject"] = f"Votre commande {number} est en préparation"
    msg["From"] = formataddr((SENDER_NAME, user))
    msg["To"] = to
    msg["Reply-To"] = user
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=user.split("@")[-1])
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    return msg


def send_mail(msg):
    host = os.environ.get("SMTP_HOST") or "smtp.zoho.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def tag_errors(query, oid):
    field = "tagsAdd" if query is TAGS_ADD_M else "tagsRemove"
    return s.gql(query, {"id": oid, "t": [TAG]})[field]["userErrors"]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if not s.have_credentials():
        return
    try:
        orders = qualifying_orders()
    except RuntimeError as e:
        if "ACCESS_DENIED" in str(e):
            sys.exit("ALERTE: the Shopify app cannot read orders / customer e-mails (read_orders, write_orders, protected "
                     "customer data access): no message can be sent. " + str(e)[:200])
        raise
    if mode == "list":
        print(f"{len(orders)} order(s) would get the 'en préparation' e-mail: {', '.join(o['name'] for o in orders)}")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"count={len(orders)}\n")
        return
    dry = os.environ.get("DRY_RUN") == "1"
    if mode == "baseline":
        for o in orders:
            print(f"{o['name']}: baseline (tag {TAG}, no e-mail)")
            if not dry:
                errs = tag_errors(TAGS_ADD_M, o["id"])
                if errs:
                    sys.exit(f"ALERTE: could not tag {o['name']}: {errs}")
        print(f"baseline: {len(orders)} order(s) {'would be ' if dry else ''}marked.")
        return
    if mode != "send":
        sys.exit("usage: order_notify.py list|baseline|send")
    ready = (os.environ.get("ORDER_NOTIFY_ENABLED") == "1" and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))
    live = bool(ready) and not dry
    if not live:
        print("DRY RUN: nothing is sent (needs ORDER_NOTIFY_ENABLED=1, SMTP_USER, SMTP_PASSWORD and DRY_RUN off).")
    sent, problems = 0, 0
    for o in orders:
        to = (o.get("email") or "").strip()
        if not EMAIL_RE.match(to):
            print(f"{o['name']}: no valid e-mail ({to!r}), skipped")
            problems += 1
            continue
        if not live:
            print(f"{o['name']}: would send to {to}")
            continue
        if sent >= MAX_PER_RUN:
            print(f"{o['name']}: left for the next run (max {MAX_PER_RUN} per run)")
            continue
        try:
            errs = tag_errors(TAGS_ADD_M, o["id"])  # the tag first: never two e-mails for one order
            if errs:
                problems += 1
                print(f"{o['name']}: tag error {errs}, not sent")
                continue
            try:
                send_mail(build_message(o, to))
            except Exception:
                tag_errors(TAGS_REMOVE_M, o["id"])  # nothing left: the next run tries again
                raise
            sent += 1
            print(f"{o['name']}: e-mail sent")
        except Exception as e:  # one order that cannot be handled must not stop the others
            problems += 1
            print(f"::warning::{o['name']}: not sent ({type(e).__name__}: {str(e)[:150]})")
    print(f"{sent} e-mail(s) sent, {problems} problem(s).")
    if problems and live:
        sys.exit(f"ALERTE: {problems} order(s) could not get the 'en préparation' e-mail; see the log.")


if __name__ == "__main__":
    main()
