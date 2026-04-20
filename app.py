from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
import razorpay
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json, os, sqlite3, random, string, time
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'velox_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── Config ───────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID     = 'rzp_test_Sf36KXKuWR4CHi'
RAZORPAY_KEY_SECRET = 'XfDYtiYlMjpBYf9vfecMpww2'
razorpay_client     = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

EMAIL_ADDRESS      = 'goutamkarmakar189@gmail.com'
EMAIL_APP_PASSWORD = 'obms fwcx cuch vjuw'

# Twilio (optional SMS) – fill in real creds if desired; falls back to email-only
TWILIO_SID   = os.environ.get('TWILIO_SID', '')
TWILIO_TOKEN = os.environ.get('TWILIO_TOKEN', '')
TWILIO_FROM  = os.environ.get('TWILIO_FROM', '')

DB = 'velox.db'

# ─── Database ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT,
            phone    TEXT UNIQUE NOT NULL,
            email    TEXT,
            created  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS otps (
            phone    TEXT PRIMARY KEY,
            otp      TEXT,
            expires  INTEGER
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_ref  TEXT UNIQUE NOT NULL,
            customer_id  INTEGER,
            phone        TEXT,
            name         TEXT,
            email        TEXT,
            service      TEXT,
            location     TEXT,
            scheduled_dt TEXT,
            amount       INTEGER,
            payment_id   TEXT,
            status       TEXT DEFAULT 'confirmed',
            pro_name     TEXT,
            created      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT,
            email     TEXT,
            city      TEXT,
            service   TEXT,
            rating    INTEGER,
            review    TEXT,
            created   TEXT DEFAULT (datetime('now'))
        );
        """)

init_db()

# ─── Helpers ──────────────────────────────────────────────────────────────────
def gen_ref():
    return 'VLX-' + datetime.now().strftime('%Y') + '-' + ''.join(random.choices(string.digits, k=6))

def send_email(to, subject, html_body):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = EMAIL_ADDRESS
        msg['To']      = to
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False

def send_sms(phone, msg_text):
    """Send SMS via Twilio if creds available, else skip."""
    if not TWILIO_SID or not TWILIO_TOKEN:
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=msg_text, from_=TWILIO_FROM, to=phone)
        return True
    except Exception as e:
        print(f'SMS error: {e}')
        return False

def send_otp_email(email, otp, name='Customer'):
    html = f"""
    <html><body style="font-family:Georgia,serif;background:#0A0A0A;color:#fff;padding:30px;">
    <div style="max-width:480px;margin:0 auto;background:#1A1A1A;border:1px solid #C9A84C;border-radius:16px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#C9A84C,#E8D5A3);padding:24px;text-align:center;">
        <h1 style="color:#0A0A0A;margin:0;font-size:26px;letter-spacing:4px;">VELOX</h1>
      </div>
      <div style="padding:32px;text-align:center;">
        <h2 style="color:#C9A84C;">Your Login OTP</h2>
        <p style="color:#A0A0A0;">Hi {name}, use the code below to log in:</p>
        <div style="background:#0A0A0A;border:2px solid #C9A84C;border-radius:12px;padding:20px;margin:24px 0;">
          <span style="font-size:42px;font-weight:700;color:#C9A84C;letter-spacing:12px;">{otp}</span>
        </div>
        <p style="color:#A0A0A0;font-size:13px;">This OTP expires in <strong style="color:#fff;">10 minutes</strong>. Do not share it with anyone.</p>
      </div>
    </div></body></html>"""
    return send_email(email, '🔐 Your VELOX Login OTP', html)

def send_order_email(order_data):
    html = f"""
    <html><body style="font-family:Georgia,serif;background:#0A0A0A;color:#fff;padding:30px;">
    <div style="max-width:600px;margin:0 auto;background:#1A1A1A;border:1px solid #C9A84C;border-radius:16px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#C9A84C,#E8D5A3);padding:30px;text-align:center;">
        <h1 style="color:#0A0A0A;margin:0;font-size:28px;letter-spacing:4px;">VELOX</h1>
        <p style="color:#0A0A0A;margin:8px 0 0;font-size:14px;">Elite Services, Delivered to Your Door</p>
      </div>
      <div style="padding:30px;">
        <h2 style="color:#C9A84C;margin-top:0;">✅ New Order Received!</h2>
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Booking Ref</td>
              <td style="padding:10px 0;color:#C9A84C;border-bottom:1px solid #2A2A2A;text-align:right;font-family:monospace;"><strong>{order_data.get('booking_ref','N/A')}</strong></td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Customer</td>
              <td style="padding:10px 0;color:#fff;border-bottom:1px solid #2A2A2A;text-align:right;"><strong>{order_data.get('name','N/A')}</strong></td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Email</td>
              <td style="padding:10px 0;color:#fff;border-bottom:1px solid #2A2A2A;text-align:right;">{order_data.get('email','N/A')}</td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Phone</td>
              <td style="padding:10px 0;color:#fff;border-bottom:1px solid #2A2A2A;text-align:right;">{order_data.get('phone','N/A')}</td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Service</td>
              <td style="padding:10px 0;color:#C9A84C;border-bottom:1px solid #2A2A2A;text-align:right;"><strong>{order_data.get('service','N/A')}</strong></td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Location</td>
              <td style="padding:10px 0;color:#fff;border-bottom:1px solid #2A2A2A;text-align:right;">{order_data.get('location','N/A')}</td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;border-bottom:1px solid #2A2A2A;">Date & Time</td>
              <td style="padding:10px 0;color:#fff;border-bottom:1px solid #2A2A2A;text-align:right;">{order_data.get('datetime','N/A')}</td></tr>
          <tr><td style="padding:10px 0;color:#A0A0A0;">Payment ID</td>
              <td style="padding:10px 0;color:#fff;text-align:right;">{order_data.get('payment_id','N/A')}</td></tr>
        </table>
        <div style="background:#0A0A0A;border:1px solid #C9A84C;border-radius:12px;padding:20px;margin-top:20px;text-align:center;">
          <p style="color:#A0A0A0;margin:0 0 8px;">Total Amount Paid</p>
          <h2 style="color:#C9A84C;margin:0;font-size:32px;">₹{order_data.get('amount',0)}</h2>
        </div>
        <div style="margin-top:20px;padding:16px;background:#111;border-radius:10px;border:1px solid #2A2A2A;">
          <p style="color:#A0A0A0;margin:0 0 6px;font-size:12px;">🔗 PARTNER TRACKING LINK (share with service professional):</p>
          <a href="{order_data.get('pro_link','#')}" style="color:#C9A84C;word-break:break-all;">{order_data.get('pro_link','N/A')}</a>
        </div>
        <p style="color:#A0A0A0;margin-top:20px;font-size:13px;">Order placed on {datetime.now().strftime('%d %B %Y at %I:%M %p')}</p>
      </div>
    </div></body></html>"""
    return send_email(EMAIL_ADDRESS, f"🎉 New VELOX Order – {order_data.get('service','Service')} | ₹{order_data.get('amount',0)}", html)

def send_booking_confirmation_customer(order_data):
    """Email sent to the customer with their booking details & tracking link."""
    html = f"""
    <html><body style="font-family:Georgia,serif;background:#0A0A0A;color:#fff;padding:30px;">
    <div style="max-width:540px;margin:0 auto;background:#1A1A1A;border:1px solid #C9A84C;border-radius:16px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#C9A84C,#E8D5A3);padding:30px;text-align:center;">
        <h1 style="color:#0A0A0A;margin:0;font-size:28px;letter-spacing:4px;">VELOX</h1>
      </div>
      <div style="padding:30px;">
        <h2 style="color:#C9A84C;">Booking Confirmed! 🎉</h2>
        <p style="color:#A0A0A0;">Hi <strong style="color:#fff;">{order_data.get('name','there')}</strong>, your booking is confirmed.</p>
        <div style="background:#0A0A0A;border:1px solid #2A2A2A;border-radius:12px;padding:20px;margin:20px 0;">
          <p style="color:#A0A0A0;margin:0 0 4px;font-size:12px;">BOOKING REFERENCE</p>
          <p style="color:#C9A84C;font-size:24px;font-weight:700;font-family:monospace;margin:0;">{order_data.get('booking_ref','N/A')}</p>
        </div>
        <table style="width:100%;border-collapse:collapse;">
          <tr><td style="padding:8px 0;color:#A0A0A0;">Service</td>
              <td style="padding:8px 0;color:#fff;text-align:right;"><strong>{order_data.get('service','N/A')}</strong></td></tr>
          <tr><td style="padding:8px 0;color:#A0A0A0;">Date & Time</td>
              <td style="padding:8px 0;color:#fff;text-align:right;">{order_data.get('datetime','N/A')}</td></tr>
          <tr><td style="padding:8px 0;color:#A0A0A0;">Amount Paid</td>
              <td style="padding:8px 0;color:#C9A84C;text-align:right;font-weight:700;">₹{order_data.get('amount',0)}</td></tr>
        </table>
        <a href="{order_data.get('track_link','#')}" style="display:block;text-align:center;background:#C9A84C;color:#0A0A0A;padding:14px;border-radius:10px;margin-top:24px;font-weight:700;text-decoration:none;">Track Your Order →</a>
        <p style="color:#A0A0A0;font-size:12px;text-align:center;margin-top:16px;">Log in at velox.app to see all your orders</p>
      </div>
    </div></body></html>"""
    return send_email(order_data.get('email', EMAIL_ADDRESS),
                      f"✅ Booking Confirmed – {order_data.get('service')} | VELOX", html)


# ─── Auth helpers ─────────────────────────────────────────────────────────────
def logged_in():
    return 'customer_id' in session

def current_customer():
    if not logged_in():
        return None
    with get_db() as conn:
        row = conn.execute('SELECT * FROM customers WHERE id=?', (session['customer_id'],)).fetchone()
    return dict(row) if row else None


# ─── Page Routes ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', customer=current_customer())

@app.route('/services')
def services():
    return render_template('services.html', customer=current_customer())

@app.route('/book')
def book():
    service = request.args.get('service', '')
    return render_template('book.html', selected_service=service,
                           razorpay_key=RAZORPAY_KEY_ID, customer=current_customer())

@app.route('/track-order')
def track_order():
    return render_template('track.html', customer=current_customer())

@app.route('/reviews')
def reviews():
    return render_template('reviews.html', customer=current_customer())

@app.route('/login')
def login_page():
    if logged_in():
        return redirect('/my-orders')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/my-orders')
def my_orders():
    if not logged_in():
        return redirect('/login')
    c = current_customer()
    with get_db() as conn:
        orders = conn.execute(
            'SELECT * FROM bookings WHERE customer_id=? ORDER BY created DESC',
            (session['customer_id'],)
        ).fetchall()
    return render_template('my_orders.html', customer=c, orders=[dict(o) for o in orders])

@app.route('/pro-drive/<booking_ref>')
def pro_drive(booking_ref):
    with get_db() as conn:
        bk = conn.execute('SELECT * FROM bookings WHERE booking_ref=?', (booking_ref,)).fetchone()
    if not bk:
        return "Booking not found", 404
    return render_template('pro_drive.html', booking=dict(bk))

@app.route('/partner-dash/<booking_ref>')
def partner_dash(booking_ref):
    with get_db() as conn:
        bk = conn.execute('SELECT * FROM bookings WHERE booking_ref=?', (booking_ref,)).fetchone()
    if not bk:
        return "Invalid booking reference.", 404
    return render_template('partner_dash.html', booking=dict(bk))


# ─── Auth API ─────────────────────────────────────────────────────────────────
@app.route('/api/send-otp', methods=['POST'])
def send_otp():
    data  = request.get_json()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    if not phone or not email:
        return jsonify({'success': False, 'error': 'Phone and email required'})

    otp     = str(random.randint(100000, 999999))
    expires = int(time.time()) + 600  # 10 min

    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO otps (phone, otp, expires) VALUES (?,?,?)',
                     (phone, otp, expires))
        # upsert customer record (create if new)
        existing = conn.execute('SELECT id,name FROM customers WHERE phone=?', (phone,)).fetchone()
        name = existing['name'] if existing else 'Customer'
        if not existing:
            conn.execute('INSERT OR IGNORE INTO customers (phone, email) VALUES (?,?)', (phone, email))
        else:
            conn.execute('UPDATE customers SET email=? WHERE phone=?', (email, phone))

    # Send email OTP
    sent_email = send_otp_email(email, otp, name)
    # Try SMS
    send_sms(phone, f'Your VELOX OTP is {otp}. Valid for 10 minutes.')

    if sent_email:
        return jsonify({'success': True, 'message': 'OTP sent to your email'})
    return jsonify({'success': False, 'error': 'Could not send OTP. Check email address.'})


@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    data  = request.get_json()
    phone = (data.get('phone') or '').strip()
    otp   = (data.get('otp') or '').strip()

    with get_db() as conn:
        row = conn.execute('SELECT * FROM otps WHERE phone=?', (phone,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'No OTP found. Please request again.'})
        if int(time.time()) > row['expires']:
            conn.execute('DELETE FROM otps WHERE phone=?', (phone,))
            return jsonify({'success': False, 'error': 'OTP expired. Please request again.'})
        if row['otp'] != otp:
            return jsonify({'success': False, 'error': 'Invalid OTP.'})
        # Clear OTP
        conn.execute('DELETE FROM otps WHERE phone=?', (phone,))
        customer = conn.execute('SELECT * FROM customers WHERE phone=?', (phone,)).fetchone()

    session.permanent = True
    session['customer_id'] = customer['id']
    session['customer_phone'] = phone
    return jsonify({'success': True, 'name': customer['name'] or 'Customer'})


@app.route('/api/update-name', methods=['POST'])
def update_name():
    if not logged_in():
        return jsonify({'success': False})
    data = request.get_json()
    name = (data.get('name') or '').strip()
    if name:
        with get_db() as conn:
            conn.execute('UPDATE customers SET name=? WHERE id=?', (name, session['customer_id']))
    return jsonify({'success': True})


# ─── Order API ────────────────────────────────────────────────────────────────
@app.route('/api/create-order', methods=['POST'])
def create_order():
    try:
        data   = request.get_json()
        amount = int(data.get('amount', 0)) * 100
        order  = razorpay_client.order.create({
            'amount': amount, 'currency': 'INR', 'payment_capture': 1,
            'notes': {
                'service': data.get('service', ''),
                'customer_name': data.get('name', ''),
                'customer_phone': data.get('phone', ''),
                'location': data.get('location', '')
            }
        })
        return jsonify({'success': True, 'order': order})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/verify-payment', methods=['POST'])
def verify_payment():
    try:
        data = request.get_json()
        params_dict = {
            'razorpay_order_id':   data.get('razorpay_order_id'),
            'razorpay_payment_id': data.get('razorpay_payment_id'),
            'razorpay_signature':  data.get('razorpay_signature')
        }
        razorpay_client.utility.verify_payment_signature(params_dict)

        # Generate booking ref
        booking_ref = gen_ref()
        customer_id = session.get('customer_id')

        # FIX: Ensure base_url is correctly handled for pro and track links
        base_url = request.host_url.rstrip('/')
        
        # We will use partner-dash as the professional's primary link
        pro_link   = f"{base_url}/partner-dash/{booking_ref}"
        track_link = f"{base_url}/track-order?ref={booking_ref}"

        order_data = {
            'booking_ref': booking_ref,
            'name':        data.get('customer_name', 'N/A'),
            'email':       data.get('customer_email', 'N/A'),
            'phone':       data.get('customer_phone', 'N/A'),
            'service':     data.get('service', 'N/A'),
            'location':    data.get('location', 'N/A'),
            'datetime':    data.get('datetime', 'N/A'),
            'amount':      data.get('amount', 0),
            'payment_id':  data.get('razorpay_payment_id', 'N/A'),
            'pro_link':    pro_link,
            'track_link':  track_link,
        }

        # Save to DB
        with get_db() as conn:
            conn.execute("""
                INSERT INTO bookings
                  (booking_ref, customer_id, phone, name, email, service, location,
                   scheduled_dt, amount, payment_id, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,'confirmed')
            """, (
                booking_ref, customer_id,
                order_data['phone'], order_data['name'], order_data['email'],
                order_data['service'], order_data['location'],
                order_data['datetime'], order_data['amount'], order_data['payment_id']
            ))

        # Notify admin (goutamkarmakar189@gmail.com) with the Professional Link
        send_order_email(order_data)
        
        # Notify customer with their Tracking Link
        if order_data['email'] and order_data['email'] != 'N/A':
            send_booking_confirmation_customer(order_data)

        return jsonify({
            'success': True,
            'booking_ref': booking_ref,
            'track_link': track_link
        })
    except razorpay.errors.SignatureVerificationError:
        return jsonify({'success': False, 'error': 'Invalid payment signature'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/get-booking/<ref>')
def get_booking(ref):
    with get_db() as conn:
        bk = conn.execute('SELECT * FROM bookings WHERE booking_ref=?', (ref,)).fetchone()
    if not bk:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'booking': dict(bk)})


@app.route('/api/update-booking-status', methods=['POST'])
def update_booking_status():
    data   = request.get_json()
    ref    = data.get('booking_ref')
    status = data.get('status')
    pro    = data.get('pro_name', '')
    with get_db() as conn:
        conn.execute('UPDATE bookings SET status=?, pro_name=? WHERE booking_ref=?',
                     (status, pro, ref))
    socketio.emit('status_update', {'booking_ref': ref, 'status': status}, room=ref)
    return jsonify({'success': True})


@app.route('/api/submit-review', methods=['POST'])
def submit_review():
    try:
        data = request.get_json()
        with get_db() as conn:
            conn.execute(
                'INSERT INTO reviews (name,email,city,service,rating,review) VALUES (?,?,?,?,?,?)',
                (data.get('name'), data.get('email'), data.get('city'),
                 data.get('service'), data.get('rating'), data.get('review'))
            )
        # Email notification
        try:
            html = f"""<html><body style="font-family:Georgia;background:#0A0A0A;color:#fff;padding:30px;">
            <div style="max-width:500px;margin:0 auto;background:#1A1A1A;border:1px solid #C9A84C;border-radius:16px;padding:30px;">
            <h2 style="color:#C9A84C;">New Review from {data.get('name')}</h2>
            <p><strong>Service:</strong> {data.get('service')}</p>
            <p><strong>Rating:</strong> {'⭐'*int(data.get('rating',5))}</p>
            <p><strong>City:</strong> {data.get('city','')}</p>
            <p><strong>Review:</strong> {data.get('review','')}</p>
            </div></body></html>"""
            send_email(EMAIL_ADDRESS, f"⭐ New VELOX Review – {data.get('rating')}/5 Stars", html)
        except:
            pass
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── SocketIO – Live Location ─────────────────────────────────────────────────
@socketio.on('join_tracking')
def on_join(data):
    """Customer joins a room for their booking."""
    ref = data.get('booking_ref')
    if ref:
        join_room(ref)

@socketio.on('update_location')
def on_location(data):
    """Pro emits location; forward to all customers tracking this booking."""
    ref = data.get('booking_ref')
    if ref:
        emit('location_update', data, room=ref)


if __name__ == '__main__':
    socketio.run(app, debug=True)
