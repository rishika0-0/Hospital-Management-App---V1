from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Admin, Doctor, Patient, Department, Appointment
from config import Config
from flask_bcrypt import Bcrypt
from datetime import date


bcrypt = Bcrypt()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    bcrypt.init_app(app)

    with app.app_context():
        db.create_all()

        # ✅ Create predefined Admin
        if not Admin.query.filter_by(username='admin').first():
            hashed_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
            admin = Admin(username='admin', password=hashed_pw, email='admin@hospital.com')
            db.session.add(admin)
            db.session.commit()
            print("✅ Default admin created: username='admin', password='admin123'")

        from models import Department
        if Department.query.count() == 0:
            default_departments = [
                Department(name="Cardiology", description="Heart specialist"),
                Department(name="Neurology", description="Brain and nervous system"),
                Department(name="Orthopedics", description="Bones and muscles"),
                Department(name="Pediatrics", description="Child health"),
                Department(name="Dermatology", description="Skin specialist"),
            ]
            db.session.bulk_save_objects(default_departments)
            db.session.commit()
            print("✅ Default departments added.")
    return app


app = create_app()

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Check Admin
        admin = Admin.query.filter_by(email=email).first()
        if admin and bcrypt.check_password_hash(admin.password, password):
            session['role'] = 'admin'
            session['user'] = admin.username
            return redirect(url_for('admin_dashboard'))

        # Check Doctor
        doctor = Doctor.query.filter_by(email=email).first()
        if doctor and bcrypt.check_password_hash(doctor.password, password):
            session['role'] = 'doctor'
            session['user'] = doctor.name
            return redirect(url_for('doctor_dashboard'))

        # Check Patient
        patient = Patient.query.filter_by(email=email).first()
        if patient and bcrypt.check_password_hash(patient.password, password):
            session['role'] = 'patient'
            session['user'] = patient.name
            return redirect(url_for('patient_dashboard'))

        flash("Invalid credentials. Please try again.", "danger")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        contact = request.form.get('contact')

        if Patient.query.filter_by(email=email).first():
            flash("Email already registered!", "warning")
            return redirect(url_for('register'))

        new_patient = Patient(name=name, email=email, password=password, contact=contact)
        db.session.add(new_patient)
        db.session.commit()
        flash("Registration successful! Please login.", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

# Utility: ensures admin-only access
def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Admin login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    # totals
    total_doctors = Doctor.query.filter_by(is_active=True).count()
    total_patients = Patient.query.filter_by(is_active=True).count()
    total_appointments = Appointment.query.count()

    # upcoming appointments next 7 days for quick view
    today = date.today()
    upcoming = Appointment.query.filter(Appointment.date >= today).order_by(Appointment.date).limit(10).all()

    return render_template('admin_dashboard.html',
                           total_doctors=total_doctors,
                           total_patients=total_patients,
                           total_appointments=total_appointments,
                           upcoming=upcoming)

def doctor_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'doctor':
            flash("Doctor login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

@app.route('/doctor')
def doctor_dashboard():
    if session.get('role') != 'doctor':
        return redirect(url_for('login'))
    return render_template('doctor_dashboard.html', user=session['user'])

def patient_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'patient':
            flash("Patient login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

@app.route('/patient')
def patient_dashboard():
    if session.get('role') != 'patient':
        return redirect(url_for('login'))
    return render_template('patient_dashboard.html', user=session['user'])

@app.route('/admin/doctors')
@admin_required
def admin_doctors():
    q = request.args.get('q')
    # allow search by name or specialization
    if q:
        doctors = Doctor.query.join(Department).filter(
            db.or_(Doctor.name.ilike(f'%{q}%'),
                   Department.name.ilike(f'%{q}%'))
        ).all()
    else:
        doctors = Doctor.query.all()
    return render_template('admin_doctors.html', doctors=doctors)

#Admin adds, Edits, Blacklists, removes Doctors
@app.route('/admin/doctors/add', methods=['GET', 'POST'])
@admin_required
def admin_add_doctor():
    departments = Department.query.all()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        dept_id = request.form['department']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        availability = request.form.get('availability')  # text field, free format or JSON-string

        if Doctor.query.filter_by(email=email).first():
            flash("Doctor email already exists", "warning")
            return redirect(url_for('admin_add_doctor'))

        doc = Doctor(name=name, email=email, password=password, specialization_id=dept_id, availability=availability)
        db.session.add(doc)
        db.session.commit()
        flash("Doctor added successfully", "success")
        return redirect(url_for('admin_doctors'))

    return render_template('admin_add_doctor.html', departments=departments)


@app.route('/admin/doctors/<int:doctor_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    departments = Department.query.all()
    if request.method == 'POST':
        doctor.name = request.form['name']
        doctor.email = request.form['email']
        doctor.specialization_id = request.form['department']
        doctor.availability = request.form.get('availability')
        pw = request.form.get('password')
        if pw:
            doctor.password = bcrypt.generate_password_hash(pw).decode('utf-8')
        db.session.commit()
        flash("Doctor updated", "success")
        return redirect(url_for('admin_doctors'))
    return render_template('admin_edit_doctor.html', doctor=doctor, departments=departments)


@app.route('/admin/doctors/<int:doctor_id>/toggle_active')
@admin_required
def admin_toggle_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_active = not doctor.is_active
    db.session.commit()
    msg = "activated" if doctor.is_active else "blacklisted"
    flash(f"Doctor {msg}.", "info")
    return redirect(url_for('admin_doctors'))

@app.route('/admin/doctors/<int:doctor_id>/delete', methods=['POST'])
@admin_required
def admin_delete_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)

    has_appointments = Appointment.query.filter_by(doctor_id=doctor_id).count() > 0
    if has_appointments:
        flash("Cannot delete doctor with existing appointments.", "warning")
        return redirect(url_for('admin_doctors'))

    db.session.delete(doctor)
    db.session.commit()
    flash("Doctor removed permanently.", "danger")
    return redirect(url_for('admin_doctors'))

@app.route('/admin/appointments')
@admin_required
def admin_appointments():
    filter_type = request.args.get('filter')  # upcoming or past
    today = date.today()
    if filter_type == 'past':
        appts = Appointment.query.filter(Appointment.date < today).order_by(Appointment.date.desc()).all()
    else:
        # default upcoming
        appts = Appointment.query.filter(Appointment.date >= today).order_by(Appointment.date).all()

    return render_template('admin_appointments.html', appointments=appts, filter_type=filter_type)

@app.route('/admin/appointments/<int:appt_id>/status', methods=['POST'])
@admin_required
def admin_change_appointment_status(appt_id):
    new_status = request.form.get('status')  # Completed / Cancelled / Booked
    appt = Appointment.query.get_or_404(appt_id)
    appt.status = new_status
    db.session.commit()
    flash("Appointment status updated", "success")
    return redirect(url_for('admin_appointments'))

#Admin searches patients
@app.route('/admin/patients')
@admin_required
def admin_patients():
    q = request.args.get('q')
    if q:
        patients = Patient.query.filter(
            db.or_(Patient.name.ilike(f'%{q}%'),
                   Patient.email.ilike(f'%{q}%'),
                   Patient.contact.ilike(f'%{q}%'),
                   Patient.id == q if q.isdigit() else False)
        ).all()
    else:
        patients = Patient.query.all()

    return render_template('admin_patients.html', patients=patients)

#To blacklist patient
@app.route('/admin/patients/<int:patient_id>/toggle_active')
@admin_required
def admin_toggle_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.is_active = not patient.is_active
    db.session.commit()
    msg = "activated" if patient.is_active else "blacklisted"
    flash(f"Patient {msg}", "info")
    return redirect(url_for('admin_patients'))

@app.route('/admin/patients/<int:patient_id>/delete', methods=['POST'])
@admin_required
def admin_delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    # Optional: prevent deletion if they have appointments
    has_appointments = Appointment.query.filter_by(patient_id=patient_id).count() > 0
    if has_appointments:
        flash("Cannot delete patient with existing appointments.", "warning")
        return redirect(url_for('admin_patients'))

    db.session.delete(patient)
    db.session.commit()
    flash("Patient removed permanently.", "danger")
    return redirect(url_for('admin_patients'))


@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
