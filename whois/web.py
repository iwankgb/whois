#!/usr/bin/python3
from whois.database import db, Device, User, post_last_seen_devices
from datetime import datetime

from flask import Flask, flash, render_template, redirect, url_for, request, \
    jsonify
from flask_login import LoginManager, login_required, current_user, login_user, \
    logout_user
from werkzeug.security import generate_password_hash

from whois import settings
from whois.utility import parse_mikrotik_data


app = Flask(__name__)
app.secret_key = settings.secret_key
login_manager = LoginManager()
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(user_id)


@app.before_request
def before_request():
    db.connect()


@app.after_request
def after_request(response):
    db.close()
    return response


@app.route('/')
def index():
    """Serve list of people in hs, show panel for logged users"""
    unclaimed = None
    mine = None
    if current_user.is_authenticated:
        cursor = db.cursor()
        recent = Device.get_recent(cursor, 12)
        unclaimed = [dev for dev in recent if dev.owner is None]
        mine = current_user.get_claimed_devices(cursor)

    return render_template('index.html',
                           devices={'unclaimed': unclaimed, 'mine': mine})


@app.route('/api/now', methods=['GET'])
def now_at_space():
    """Send list of people currently in HS as JSON, only registred people,
    used by other services in HS,
    requests should be from hs3.pl domain or from HSWAN"""
    cursor = db.cursor()
    devices = Device.get_recent(cursor)
    user_ids = set(
        [device.owner for device in devices if device.owner is not None])
    users = [str(User.get_by_id(id)) for id in user_ids]

    return jsonify({"users": sorted(users),
                    "user_count": len(users),
                    "unknown_dev": len(
                        [dev for dev in devices if dev.owner is None])})


@app.route('/api/last_seen', methods=['POST'])
def last_seen_devices():
    """Post devices last seen by mikrotik to database
    Listen only for whitelisted devices"""
    if request.remote_addr in settings.whitelist:
        data = request.get_json()
        parsed_data = parse_mikrotik_data(datetime.now(), data)

        cursor = db.cursor()
        post_last_seen_devices(cursor, parsed_data)
        db.commit()


@app.route('/device/<mac_addr>', methods=['GET', 'POST'])
@login_required
def device(mac_addr):
    """Get info about device, claim device, release device"""
    cursor = db.cursor()
    dev = Device.get_by_mac(cursor, mac_addr)
    if request.method == 'POST':
        print('Got action: ' + request.values.get('action'))
        if request.values.get('action') == 'claim':
            dev.claim(cursor, current_user.get_id())
            flash('Claimed {}!'.format(mac_addr), 'alert-success')

        elif request.values.get('action') == 'unclaim':
            dev.unclaim(cursor)
            flash('Unclaimed {}!'.format(mac_addr), 'alert-info')

        if request.values.get('tags'):
            flash('Can\'t set tags to {}! Unimplemented'.format(mac_addr),
                  'alert-danger')

    db.commit()

    return render_template('device.html',
                           device={'mac_addr': dev.mac_addr,
                                   'last_seen': dev.last_seen,
                                   'claim': str(User.get_by_id(cursor,
                                                               dev.user_id))})


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Registration form"""
    if request.method == 'POST':
        # TODO: WTF forms dla lepszego bezpieczeństwa
        display_name = request.form['display_name']
        login = request.form['username']
        password = generate_password_hash(request.form['password'])

        cursor = db.cursor()
        User.register(cursor, login, display_name, password)
        db.commit()
        flash('Registered.', 'alert-info')

        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login using naive db or LDAP (work on it @priest)"""
    if request.method == 'POST':
        cursor = db.cursor()
        user = User.get_by_login(cursor, request.form['username'])
        if user is not None and user.auth(cursor,
                                          request.form['password']) == True:
            login_user(user)
            flash(
                'Hello {}! You can now claim and manage your devices.'.format(
                    current_user.login), 'alert-success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials', 'alert-danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'alert-info')
    return redirect(url_for('index'))