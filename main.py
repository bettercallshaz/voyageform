from nicegui import ui
from supabase import create_client, Client
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import resend

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@voyageform.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

current_user_email = None
current_role = None
current_user_id = None

# ====================== Timestamp Formatter ======================
def format_timestamp(ts=None):
    try:
        if ts is None:
            dt = datetime.now(timezone.utc)
        elif isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            dt = ts
        base = dt.strftime('%d %B %Y %H:%M')
        offset = dt.utcoffset()
        offset_str = "UTC" if offset is None else f"UTC{int(offset.total_seconds() // 3600):+d}"
        return f"{base} {offset_str}"
    except:
        return str(ts)[:19] if ts else "—"

# ====================== PDF ======================
def create_pdf(rfq_text: str, broker_details: str = "", status_history: str = "", 
               requester_details: str = "", broker_remarks: str = ""):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    y = 750

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, "WAR RISK QUOTATION REQUEST (RFQ)")
    y -= 40

    if broker_details:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "Selected Broker Details:")
        y -= 25
        c.setFont("Helvetica", 11)
        for line in broker_details.split('\n'):
            if line.strip():
                c.drawString(50, y, line.strip())
                y -= 18
        y -= 15

    if requester_details:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(50, y, "Requester Details:")
        y -= 25
        c.setFont("Helvetica", 11)
        for line in requester_details.split('\n'):
            if line.strip():
                c.drawString(50, y, line.strip())
                y -= 18
        y -= 15

    c.setFont("Helvetica", 11)
    for line in rfq_text.split('\n'):
        if line.strip():
            c.drawString(50, y, line.strip())
            y -= 18
            if y < 80:
                c.showPage()
                y = 750

    if broker_remarks and broker_remarks.strip():
        y -= 25
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Broker Remarks / Notes:")
        y -= 20
        c.setFont("Helvetica", 10)
        for line in broker_remarks.split('\n'):
            if line.strip():
                c.drawString(50, y, line.strip())
                y -= 16
                if y < 80:
                    c.showPage()
                    y = 750

    if status_history:
        y -= 25
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Audit Trail:")
        y -= 20
        c.setFont("Helvetica", 10)
        for line in status_history.split('\n'):
            if line.strip():
                c.drawString(50, y, line.strip())
                y -= 16
                if y < 80:
                    c.showPage()
                    y = 750

    c.save()
    buffer.seek(0)
    return buffer

# ====================== AUTH ======================
def ensure_profile_exists():
    if not current_user_id: return
    try:
        if not supabase.table("profiles").select("id").eq("id", current_user_id).execute().data:
            supabase.table("profiles").insert({
                "id": current_user_id,
                "role": current_role,
                "company_name": current_user_email.split('@')[0]
            }).execute()
    except:
        pass

def logout():
    global current_user_email, current_role, current_user_id
    current_user_email = current_role = current_user_id = None
    ui.notify('✅ Logged out', type='positive')
    ui.navigate.to('/')

def handle_login(email: str, password: str, chosen_role: str):
    global current_user_email, current_role, current_user_id
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = response.user
        if user.user_metadata.get('role') != chosen_role:
            ui.notify(f'❌ Wrong role', type='negative')
            return
        current_user_email = user.email
        current_user_id = user.id
        current_role = chosen_role
        ensure_profile_exists()
        ui.notify(f'✅ Logged in as {chosen_role}', type='positive')
        ui.navigate.to('/requester' if chosen_role == 'requester' else '/broker')
    except:
        ui.notify('❌ Invalid credentials', type='negative')

def handle_register(email: str, password: str, company: str, role: str, broker_name=None, office=None):
    try:
        response = supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"role": role}}})
        user_id = response.user.id

        supabase.table("profiles").upsert({"id": user_id, "role": role, "company_name": company or email.split('@')[0]}).execute()

        if role == 'broker' and broker_name:
            supabase.table("brokers").upsert({
                "id": user_id, "broker_name": broker_name, "company_name": company or email.split('@')[0],
                "contact_email": email, "office_details": office or ""
            }).execute()

        ui.notify(f'✅ {role.capitalize()} registered!', type='positive')
        ui.navigate.to('/')
    except Exception as e:
        ui.notify(f'❌ {str(e)}', type='negative')

# ====================== EMAIL ======================
def send_email(to_email, subject, html_content):
    if not RESEND_API_KEY:
        print("⚠️ RESEND_API_KEY not set")
        return False
    
    try:
        response = resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_content
        })
        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email failed to {to_email}: {str(e)}")
        ui.notify(f'Email failed: {str(e)[:80]}...', type='negative')
        return False

# ====================== REQUESTER DASHBOARD ======================
@ui.page('/requester')
def requester_dashboard():
    if not current_user_email or current_role != 'requester':
        ui.navigate.to('/')
        return

    with ui.row().classes('justify-between items-center w-full max-w-4xl mx-auto mt-8'):
        ui.label(f'👋 Requester Dashboard - {current_user_email}').classes('text-3xl font-bold')
        ui.button('Logout', on_click=logout).classes('bg-red-600')

    ui.button('GENERATE NEW RFQ', on_click=lambda: ui.navigate.to('/generate')).classes('mt-8 bg-blue-600')

    ui.label('Your Generated RFQs').classes('text-xl mt-10 mb-4')

    rfqs = supabase.table("rfqs").select("*, brokers!broker_id(broker_name, contact_email, office_details)")\
        .eq("requester_id", current_user_id).order("generated_at", desc=True).execute().data or []

    for r in rfqs:
        with ui.card().classes('w-full p-6 mb-6'):
            ui.label(f"RFQ {r['rfq_id']} — {r.get('cargo', 'N/A')}").classes('font-bold text-lg')
            ui.label(f"Status: {r.get('status', 'Generated')}").classes('text-blue-600')
            last_update = r.get('status_history', '').split('\n')[-1] if r.get('status_history') else '—'
            ui.label(f"Last updated: {last_update}").classes('text-sm text-gray-500')

            viewed = r.get('requester_viewed', False)
            viewed_at = r.get('requester_viewed_at')

            with ui.row().classes('gap-4 mt-4 items-center'):
                if viewed and viewed_at:
                    ui.label(f'✅ Read on {format_timestamp(viewed_at)}').classes('text-green-600 font-medium')
                else:
                    ui.button('📬 Mark as Read', on_click=lambda r=r: mark_as_read(r['id'])).classes('bg-gray-600')

                ui.button('Download PDF', 
                          on_click=lambda r=r: ui.download(
                              create_pdf(
                                  r['full_rfq_text'],
                                  f"""Selected Broker: {r.get('brokers', {}).get('broker_name', 'N/A')}
Email: {r.get('brokers', {}).get('contact_email', 'N/A')}
Office: {r.get('brokers', {}).get('office_details', 'N/A')}""",
                                  r.get('status_history', ''),
                                  f"""Company: {r.get('company_name', 'N/A')}
Email: {r.get('contact_email', 'N/A')}""",
                                  r.get('broker_remarks', '')
                              ).getvalue(), f"{r['rfq_id']}.pdf"
                          )).classes('bg-green-600')

def mark_as_read(rfq_id):
    try:
        supabase.table("rfqs").update({
            "requester_viewed": True,
            "requester_viewed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", rfq_id).execute()
        ui.notify('✅ Marked as Read', type='positive')
        ui.navigate.to('/requester')
    except Exception as e:
        ui.notify(f'❌ {str(e)}', type='negative')

# ====================== GENERATE RFQ ======================
@ui.page('/generate')
def generate_rfq():
    if not current_user_email or current_role != 'requester':
        ui.navigate.to('/')
        return

    with ui.card().classes('w-full max-w-2xl mx-auto mt-10 p-8'):
        ui.label('Create New War Risk RFQ').classes('text-3xl font-bold mb-8')

        company = ui.input('Company Name', value=current_user_email.split('@')[0]).classes('w-full')
        vessel_flag = ui.input('Vessel Flag', value='Malaysia').classes('w-full')
        hull_value = ui.number('Hull Value (USD)', value=250000000, min=100000).classes('w-full')
        cargo_type = ui.select(['Crude Oil / Petroleum', 'Urea (Fertilizer)', 'Ammonia', 'Bulk Grain / Food', 'Other'], label='Cargo Type').classes('w-full')
        voyage_route = ui.input('Voyage Route').classes('w-full')

        dfc_toggle = ui.checkbox('Apply for DFC Facility (US Maritime Reinsurance)')

        with ui.column().classes('w-full gap-4 mt-4') as dfc_fields:
            dfc_fields.visible = False
            vessel_name = ui.input('Vessel Name and Operator').classes('w-full')
            origin_dest = ui.input('Origin and Destination Country').classes('w-full')
            imo = ui.input('IMO Number').classes('w-full')
            flag_vessel = ui.input('Flag of the Vessel').classes('w-full')
            operator_crew = ui.input('Vessel Operator and Crew').classes('w-full')
            beneficial = ui.input('Major Beneficial Owners').classes('w-full')
            registered = ui.input('Registered Owner').classes('w-full')
            cargo_info = ui.input('Cargo Details').classes('w-full')
            cargo_owner = ui.input('Cargo Owner').classes('w-full')
            lenders = ui.input('Lenders Information').classes('w-full')

        def toggle_dfc():
            dfc_fields.visible = dfc_toggle.value
        dfc_toggle.on_value_change(toggle_dfc)

        cargo_hint = ui.label('').classes('text-xs text-amber-600 mt-1')
        def on_cargo_change(e):
            cargo_hint.text = 'Other - please specify in Remarks / Additional Notes' if e.value == 'Other' else ''
        cargo_type.on_value_change(on_cargo_change)

        remarks = ui.textarea('Remarks / Additional Notes (optional)').classes('w-full').props('rows=4')

        brokers = supabase.table("brokers").select("id, broker_name, contact_email, office_details").execute().data
        broker_dict = {b["broker_name"]: b for b in brokers if b.get("broker_name")}
        broker_options = [f"{b['broker_name']} - {b.get('office_details', 'N/A')} ({b.get('contact_email', '')})" for b in brokers if b.get("broker_name")]
        selected_broker = ui.select(options=broker_options, label='Select Broker').classes('w-full')

        def submit():
            if not selected_broker.value:
                ui.notify('Please select a broker', type='negative')
                return

            broker_name = selected_broker.value.split(' - ')[0].strip()
            broker = broker_dict.get(broker_name)

            rfq_text = f"Generated: {format_timestamp()}\n"
            rfq_text += f"Voyage: {voyage_route.value}\n"
            rfq_text += f"Vessel Flag: {vessel_flag.value}\n"
            rfq_text += f"Hull Value: USD {hull_value.value:,.0f}\n"
            rfq_text += f"Cargo: {cargo_type.value}\n"
            rfq_text += f"DFC Facility: {'Yes' if dfc_toggle.value else 'No'}\n"

            if dfc_toggle.value:
                rfq_text += "\nDFC Additional Information:\n"
                rfq_text += f"Vessel Name and Operator: {vessel_name.value or 'N/A'}\n"
                rfq_text += f"Origin/Destination Country: {origin_dest.value or 'N/A'}\n"
                rfq_text += f"IMO Number: {imo.value or 'N/A'}\n"
                rfq_text += f"Flag of the Vessel: {flag_vessel.value or 'N/A'}\n"
                rfq_text += f"Vessel Operator and Crew: {operator_crew.value or 'N/A'}\n"
                rfq_text += f"Major Beneficial Owners: {beneficial.value or 'N/A'}\n"
                rfq_text += f"Registered Owner: {registered.value or 'N/A'}\n"
                rfq_text += f"Types, Quantity, Origin, Destination, Value of Cargo: {cargo_info.value or 'N/A'}\n"
                rfq_text += f"Owner of Cargo and Domicile: {cargo_owner.value or 'N/A'}\n"
                rfq_text += f"Information as to Lenders: {lenders.value or 'N/A'}\n"

            if remarks.value and remarks.value.strip():
                rfq_text += f"\nRemarks:\n{remarks.value.strip()}"

            try:
                response = supabase.table("rfqs").insert({
                    "rfq_id": f"WRM-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "requester_id": current_user_id,
                    "broker_id": broker["id"],
                    "company_name": company.value,
                    "contact_email": current_user_email,
                    "cargo": cargo_type.value,
                    "full_rfq_text": rfq_text,
                    "status": "Generated",
                    "status_history": f"Generated: {format_timestamp()}",
                    "broker_name": broker_name,
                    "broker_email": broker.get("contact_email"),
                    "remarks": remarks.value.strip() if remarks.value else None
                }).execute()

                rfq_id = response.data[0]['rfq_id']

                # Send email to broker
                broker_email = broker.get("contact_email")
                if broker_email and RESEND_API_KEY:
                    html = f"""
                    <h2>New War Risk RFQ Assigned</h2>
                    <p><strong>RFQ ID:</strong> {rfq_id}</p>
                    <p><strong>Requester:</strong> {company.value}</p>
                    <p><strong>Cargo:</strong> {cargo_type.value}</p>
                    <p><strong>Voyage:</strong> {voyage_route.value}</p>
                    <p>Please login to review and respond.</p>
                    """
                    send_email(broker_email, f"New RFQ #{rfq_id} Assigned", html)

                broker_details = f"""Selected Broker: {broker_name}
Email: {broker.get('contact_email', 'N/A')}
Office: {broker.get('office_details', 'N/A')}"""

                requester_details = f"""Company: {company.value}
Email: {current_user_email}"""

                pdf_buffer = create_pdf(rfq_text, broker_details, f"Generated: {format_timestamp()}", requester_details)
                ui.download(pdf_buffer.getvalue(), f"RFQ_{datetime.now().strftime('%Y%m%d')}.pdf")
                ui.notify('✅ RFQ Generated!', type='positive')
                ui.navigate.to('/requester')
            except Exception as e:
                ui.notify(f'❌ Error: {str(e)}', type='negative')

        ui.button('GENERATE RFQ & DOWNLOAD PDF', on_click=submit).classes('w-full mt-10 bg-blue-600')

# ====================== BROKER DASHBOARD ======================
@ui.page('/broker')
def broker_dashboard():
    if not current_user_email or current_role != 'broker':
        ui.navigate.to('/')
        return

    with ui.row().classes('justify-between items-center w-full max-w-4xl mx-auto mt-8'):
        ui.label(f'🧑‍💼 Broker Dashboard - {current_user_email}').classes('text-3xl font-bold')
        ui.button('Logout', on_click=logout).classes('bg-red-600')

    ui.label('Assigned RFQs').classes('text-xl mt-10 mb-4')

    try:
        rfqs = supabase.table("rfqs")\
            .select("*, profiles!requester_id(company_name), brokers!broker_id(broker_name, contact_email, office_details)")\
            .eq("broker_id", current_user_id)\
            .order("generated_at", desc=True)\
            .execute().data or []
    except Exception as e:
        ui.notify(f"Error loading RFQs: {str(e)}", type='negative')
        rfqs = []

    if not rfqs:
        ui.label('No RFQs assigned to you yet.').classes('text-gray-500 italic')
        return

    for r in rfqs:
        with ui.card().classes('w-full p-6 mb-6'):
            ui.label(f"RFQ {r['rfq_id']} — {r.get('cargo', 'N/A')}").classes('font-bold text-lg')
            
            requester_company = r.get('company_name') or (r.get('profiles') or {}).get('company_name', 'N/A')
            ui.label(f"Requester: {requester_company}").classes('text-gray-600')
            
            ui.label(f"Status: {r.get('status', 'Generated')}").classes('text-blue-600')

            last_update = r.get('status_history', '').split('\n')[-1] if r.get('status_history') else '—'
            ui.label(f"Last updated: {last_update}").classes('text-sm text-gray-500')

            broker_remarks_input = ui.textarea('Your Notes / Remarks (optional)').classes('w-full mt-4').props('rows=3')

            viewed = r.get('broker_viewed', False)
            viewed_at = r.get('broker_viewed_at')

            new_status = ui.select(
                ["Generated", "Sent to Broker", "Quote Received", "Deal Closed"],
                value=r.get('status', 'Generated'),
                label="Update Status"
            ).classes('w-full mt-4')

            with ui.row().classes('gap-4 mt-4 items-center'):
                if viewed and viewed_at:
                    ui.label(f'✅ Read on {format_timestamp(viewed_at)}').classes('text-green-600 font-medium')
                else:
                    ui.button('📬 Mark as Read', on_click=lambda r=r: mark_as_read_broker(r['id'])).classes('bg-gray-600')

                ui.button('Update Status & Save Notes', 
                          on_click=lambda r=r, s=new_status, notes=broker_remarks_input: 
                              update_status(r['id'], s.value, notes.value if notes else "")).classes('bg-blue-600')

                ui.button('Download PDF', 
                          on_click=lambda r=r: ui.download(
                              create_pdf(
                                  r['full_rfq_text'],
                                  f"""Selected Broker: {r.get('broker_name', 'N/A')}
Email: {current_user_email}
Office: {r.get('brokers', {}).get('office_details', r.get('office_details', 'N/A'))}""",
                                  r.get('status_history', ''),
                                  f"""Company: {r.get('company_name', 'N/A')}
Email: {r.get('contact_email', 'N/A')}""",
                                  r.get('broker_remarks', '')
                              ).getvalue(), f"{r['rfq_id']}.pdf"
                          )).classes('bg-green-600')

def update_status(rfq_id, new_status, broker_notes=""):
    try:
        now_str = format_timestamp()
        new_entry = f"{new_status}: {now_str}"

        current_data = supabase.table("rfqs").select("status_history, broker_remarks").eq("id", rfq_id).execute().data
        current = current_data[0] if current_data else {}

        history = current.get("status_history", "") or ""
        updated_history = (history + "\n" + new_entry).strip()

        current_remarks = current.get("broker_remarks") or ""
        if broker_notes and broker_notes.strip():
            new_note = f"Broker Note ({now_str}): {broker_notes.strip()}"
            updated_remarks = (current_remarks + "\n" + new_note).strip() if current_remarks else new_note
        else:
            updated_remarks = current_remarks

        supabase.table("rfqs").update({
            "status": new_status,
            "status_history": updated_history,
            "broker_remarks": updated_remarks,
            "broker_viewed": False,
            "broker_viewed_at": None,
            "requester_viewed": False,
            "requester_viewed_at": None
        }).eq("id", rfq_id).execute()

        # Send email to requester
        rfq_data = supabase.table("rfqs").select("contact_email, rfq_id").eq("id", rfq_id).execute().data
        if rfq_data and rfq_data[0].get("contact_email"):
            html = f"""
            <h2>RFQ Status Updated</h2>
            <p><strong>RFQ ID:</strong> {rfq_data[0]['rfq_id']}</p>
            <p><strong>New Status:</strong> {new_status}</p>
            <p>Login to view details.</p>
            """
            send_email(rfq_data[0]["contact_email"], f"RFQ #{rfq_data[0]['rfq_id']} Updated", html)

        ui.notify(f'✅ Status updated to {new_status}', type='positive')
        ui.navigate.to('/broker')
    except Exception as e:
        ui.notify(f'❌ {str(e)}', type='negative')

def mark_as_read_broker(rfq_id):
    try:
        supabase.table("rfqs").update({
            "broker_viewed": True,
            "broker_viewed_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", rfq_id).execute()
        ui.notify('✅ Marked as Read', type='positive')
        ui.navigate.to('/broker')
    except Exception as e:
        ui.notify(f'❌ {str(e)}', type='negative')

# ====================== LOGIN & REGISTER ======================
@ui.page('/')
def login_page():
    with ui.card().classes('w-full max-w-md mx-auto mt-20 p-8'):
        ui.label('⚓ VoyageForm').classes('text-4xl font-bold text-center mb-2')
        ui.label('Secure Marine RFQ Platform').classes('text-center text-gray-500 mb-8')

        email = ui.input('Email').classes('w-full')
        password = ui.input('Password', password=True).classes('w-full')

        with ui.row().classes('w-full gap-4 mt-6'):
            ui.button('LOGIN AS REQUESTER', on_click=lambda: handle_login(email.value, password.value, 'requester')).classes('flex-1 bg-blue-600')
            ui.button('LOGIN AS BROKER', on_click=lambda: handle_login(email.value, password.value, 'broker')).classes('flex-1 bg-green-600')

        ui.separator().classes('my-6')
        with ui.row().classes('w-full gap-4'):
            ui.button('REGISTER AS REQUESTER', on_click=lambda: ui.navigate.to('/register_requester')).classes('flex-1 bg-blue-500')
            ui.button('REGISTER AS BROKER', on_click=lambda: ui.navigate.to('/register_broker')).classes('flex-1 bg-green-500')

@ui.page('/register_requester')
def register_requester_page():
    with ui.card().classes('w-full max-w-md mx-auto mt-20 p-8'):
        ui.label('Register as Requester').classes('text-2xl font-bold mb-6')
        email = ui.input('Email').classes('w-full')
        password = ui.input('Password', password=True).classes('w-full')
        company = ui.input('Company Name').classes('w-full')
        ui.button('REGISTER', on_click=lambda: handle_register(email.value, password.value, company.value, 'requester')).classes('w-full mt-6 bg-blue-600')
        ui.button('BACK', on_click=lambda: ui.navigate.to('/')).classes('w-full mt-2')

@ui.page('/register_broker')
def register_broker_page():
    with ui.card().classes('w-full max-w-md mx-auto mt-20 p-8'):
        ui.label('Register as Broker').classes('text-2xl font-bold mb-6')
        email = ui.input('Email').classes('w-full')
        password = ui.input('Password', password=True).classes('w-full')
        broker_name = ui.input('Broker Name').classes('w-full')
        company = ui.input('Company Name').classes('w-full')
        office = ui.input('Office Details').classes('w-full')
        ui.button('REGISTER', on_click=lambda: handle_register(email.value, password.value, company.value, 'broker', broker_name.value, office.value)).classes('w-full mt-6 bg-green-600')
        ui.button('BACK', on_click=lambda: ui.navigate.to('/')).classes('w-full mt-2')

ui.run(title='VoyageForm', favicon='⚓', port=8081, reload=False)
