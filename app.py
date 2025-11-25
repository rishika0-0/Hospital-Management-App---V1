from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Admin, Doctor, Patient, Department, Appointment, Treatment, DoctorAvailability
from config import Config
from flask_bcrypt import Bcrypt
from datetime import date, timedelta, time as dt_time, datetime
import re

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

        # ✅ Default departments
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

# ---------- AVAILABILITY PARSING & SLOT GENERATION HELPERS ---------- #

WEEKDAY_MAP = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}

def parse_availability_string(avail_str):
    """
    Expected format: 'Mon–Fri: 07:00–13:00'
    Returns: (start_weekday, end_weekday, start_time, end_time)
    Or None if invalid.
    """
    if not avail_str:
        return None

    # Replace en-dash with normal hyphen just in case
    avail_str = avail_str.replace("–", "-")

    # Example normalized: 'Mon-Fri: 07:00-13:00'
    pattern = r"([A-Za-z]{3})-([A-Za-z]{3})\s*:\s*([0-9]{2}:[0-9]{2})-([0-9]{2}:[0-9]{2})"
    m = re.match(pattern, avail_str.strip())
    if not m:
        return None

    start_day, end_day, start_t_str, end_t_str = m.groups()

    if start_day not in WEEKDAY_MAP or end_day not in WEEKDAY_MAP:
        return None

    start_weekday = WEEKDAY_MAP[start_day]
    end_weekday = WEEKDAY_MAP[end_day]

    start_hour, start_minute = map(int, start_t_str.split(":"))
    end_hour, end_minute = map(int, end_t_str.split(":"))

    start_time = dt_time(start_hour, start_minute)
    end_time = dt_time(end_hour, end_minute)

    if datetime.combine(date.today(), end_time) <= datetime.combine(date.today(), start_time):
        return None

    return start_weekday, end_weekday, start_time, end_time


def regenerate_availability_slots(doctor):
    """
    Clears old DoctorAvailability for this doc for the next 7 days
    and regenerates 1-hour slots based on doctor.availability.
    """
    parsed = parse_availability_string(doctor.availability)
    if not parsed:
        print("⚠️ Could not parse availability:", doctor.availability)
        return

    start_wd, end_wd, start_time, end_time = parsed

    # Delete existing upcoming slots
    today = date.today()
    week_later = today + timedelta(days=7)

    DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor.id,
        DoctorAvailability.date >= today,
        DoctorAvailability.date <= week_later
    ).delete()
    db.session.commit()

    # Generate 1-hour slots for each day in next 7 days
    day_count = (week_later - today).days + 1
    for offset in range(day_count):
        current_date = today + timedelta(days=offset)
        wd = current_date.weekday()  # 0 = Monday

        # Check if this weekday is within the availability range
        if start_wd <= end_wd:
            in_range = start_wd <= wd <= end_wd
        else:
            # Wrap-around like Fri–Mon
            in_range = wd >= start_wd or wd <= end_wd

        if not in_range:
            continue

        # Now create 1-hour blocks between start_time and end_time
        start_dt = datetime.combine(current_date, start_time)
        end_dt = datetime.combine(current_date, end_time)

        current = start_dt
        while current + timedelta(hours=1) <= end_dt:
            slot_start = current.time()
            slot_end = (current + timedelta(hours=1)).time()

            slot = DoctorAvailability(
                doctor_id=doctor.id,
                date=current_date,
                start_time=slot_start,
                end_time=slot_end,
                is_available=True
            )
            db.session.add(slot)
            current += timedelta(hours=1)

    db.session.commit()
    print(f"✅ Regenerated slots for doctor {doctor.id} for next 7 days.")


# ------------------------ AUTH & COMMON ROUTES ------------------------ #

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
            session['doctor_id'] = doctor.id
            return redirect(url_for('doctor_dashboard'))

        # Check Patient
        patient = Patient.query.filter_by(email=email).first()
        if patient and bcrypt.check_password_hash(patient.password, password):
            session['role'] = 'patient'
            session['user'] = patient.name
            session['patient_id'] = patient.id
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


# --------- ROLE DECORATORS --------- #

def admin_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Admin login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)

    return wrapper

def doctor_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'doctor':
            flash("Doctor login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)

    return wrapper


def patient_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'patient':
            flash("Patient login required", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)

    return wrapper


# ------------------------ ADMIN ROUTES ------------------------ #

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_doctors = Doctor.query.filter_by(is_active=True).count()
    total_patients = Patient.query.filter_by(is_active=True).count()
    total_appointments = Appointment.query.count()

    today = date.today()
    upcoming = Appointment.query.filter(
        Appointment.date >= today
        ).order_by(Appointment.date, Appointment.start_time).limit(10).all()
    
    print("Upcoming count:", len(upcoming))
    for a in upcoming:
        print("Appt", a.id, a.date, a.start_time, a.end_time, a.status)

    return render_template(
        'admin_dashboard.html',
        total_doctors=total_doctors,
        total_patients=total_patients,
        total_appointments=total_appointments,
        upcoming=upcoming
    )


@app.route('/admin/doctors')
@admin_required
def admin_doctors():
    q = request.args.get('q')
    if q:
        doctors = Doctor.query.join(Department).filter(
            db.or_(Doctor.name.ilike(f'%{q}%'),
                   Department.name.ilike(f'%{q}%'))
        ).all()
    else:
        doctors = Doctor.query.all()
    return render_template('admin_doctors.html', doctors=doctors)


@app.route('/admin/doctors/add', methods=['GET', 'POST'])
@admin_required
def admin_add_doctor():
    departments = Department.query.all()
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        dept_id = request.form['department']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')
        availability = request.form.get('availability')  # e.g. "Mon-Fri 07:00-13:00"

        if Doctor.query.filter_by(email=email).first():
            flash("Doctor email already exists", "warning")
            return redirect(url_for('admin_add_doctor'))

        doc = Doctor(
            name=name,
            email=email,
            password=password,
            specialization_id=dept_id,
            availability=availability
        )
        db.session.add(doc)
        db.session.commit()

        # 🔁 generate 1-hour slots for the next 7 days based on availability
        regenerate_availability_slots(doc)

        flash("Doctor added successfully", "success")
        return redirect(url_for('admin_doctors'))

    return render_template('admin_add_doctor.html', departments=departments)


@app.route('/admin/doctors/<int:doctor_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    departments = Department.query.all()
    if request.method == 'POST':
        old_avail = doctor.availability

        doctor.name = request.form['name']
        doctor.email = request.form['email']
        doctor.specialization_id = request.form['department']
        doctor.availability = request.form.get('availability')

        pw = request.form.get('password')
        if pw:
            doctor.password = bcrypt.generate_password_hash(pw).decode('utf-8')

        db.session.commit()

        # if availability changed, regenerate slots
        if doctor.availability != old_avail:
            regenerate_availability_slots(doctor)

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
    filter_type = request.args.get('filter')
    today = date.today()
    if filter_type == 'past':
        appts = Appointment.query.filter(
            Appointment.date < today
        ).order_by(Appointment.date.desc(), Appointment.start_time.desc()).all()
    else:
        appts = Appointment.query.filter(
            Appointment.date >= today
        ).order_by(Appointment.date, Appointment.start_time).all()

    return render_template('admin_appointments.html', appointments=appts, filter_type=filter_type)


@app.route('/admin/appointments/<int:appt_id>/status', methods=['POST'])
@admin_required
def admin_change_appointment_status(appt_id):
    new_status = request.form.get('status')
    appt = Appointment.query.get_or_404(appt_id)
    appt.status = new_status
    db.session.commit()
    flash("Appointment status updated", "success")
    return redirect(url_for('admin_appointments'))

@app.route('/admin/patients')
@admin_required
def admin_patients():
    q = request.args.get('q')
    if q:
        patients = Patient.query.filter(
            db.or_(
                Patient.name.ilike(f'%{q}%'),
                Patient.email.ilike(f'%{q}%'),
                Patient.contact.ilike(f'%{q}%'),
                Patient.id == q if q.isdigit() else False
            )
        ).all()
    else:
        patients = Patient.query.all()

    return render_template('admin_patients.html', patients=patients)


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
    has_appointments = Appointment.query.filter_by(patient_id=patient_id).count() > 0
    if has_appointments:
        flash("Cannot delete patient with existing appointments.", "warning")
        return redirect(url_for('admin_patients'))

    db.session.delete(patient)
    db.session.commit()
    flash("Patient removed permanently.", "danger")
    return redirect(url_for('admin_patients'))

@app.route('/admin/patients/<int:patient_id>/history')
@admin_required
def admin_patient_history(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    # All appointments for this patient (past + future), newest first
    appointments = (
        Appointment.query
        .filter_by(patient_id=patient.id)
        .order_by(Appointment.date.desc(), Appointment.start_time.desc())
        .all()
    )

    return render_template(
        'admin_patient_history.html',
        patient=patient,
        appointments=appointments
    )


# ------------------------ DOCTOR ROUTES ------------------------ #

@app.route('/doctor')
@doctor_required
def doctor_dashboard():
    doctor_id = session.get('doctor_id')
    today = date.today()
    week_later = today + timedelta(days=7)

    weekly_appointments = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date >= today,
        Appointment.date <= week_later
    ).order_by(Appointment.date, Appointment.start_time).all()

    todays_appointments = [a for a in weekly_appointments if a.date == today]

    return render_template(
        'doctor_dashboard.html',
        user=session.get('user'),
        todays_appointments=todays_appointments,
        weekly_appointments=weekly_appointments
    )


@app.route('/doctor/appointments/<int:appt_id>', methods=['GET', 'POST'])
@doctor_required
def doctor_view_appointment(appt_id):
    doctor_id = session.get('doctor_id')
    appt = Appointment.query.get_or_404(appt_id)

    if appt.doctor_id != doctor_id:
        flash("You are not allowed to access this appointment.", "danger")
        return redirect(url_for('doctor_dashboard'))

    if request.method == 'POST':
        status = request.form.get('status')
        if status in ['Booked', 'Completed', 'Cancelled']:
            appt.status = status

        diagnosis = request.form.get('diagnosis')
        prescription = request.form.get('prescription')
        notes = request.form.get('notes')

        if appt.treatment:
            appt.treatment.diagnosis = diagnosis
            appt.treatment.prescription = prescription
            appt.treatment.notes = notes
        else:
            treatment = Treatment(
                appointment_id=appt.id,
                diagnosis=diagnosis,
                prescription=prescription,
                notes=notes
            )
            db.session.add(treatment)

        db.session.commit()
        flash("Appointment and treatment updated.", "success")
        return redirect(url_for('doctor_view_appointment', appt_id=appt.id))

    return render_template('doctor_appointment_detail.html', appt=appt)


@app.route('/doctor/patients/<int:patient_id>/history')
@doctor_required
def doctor_patient_history(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    appointments = Appointment.query.filter_by(
        patient_id=patient_id
    ).order_by(Appointment.date.desc(), Appointment.start_time.desc()).all()

    return render_template('doctor_patient_history.html', patient=patient, appointments=appointments)


@app.route('/doctor/availability', methods=['GET', 'POST'])
@doctor_required
def doctor_manage_availability():
    doctor = Doctor.query.get_or_404(session.get('doctor_id'))

    if request.method == 'POST':
        doctor.availability = request.form.get('availability')
        db.session.commit()
        regenerate_availability_slots(doctor)
        flash("Availability updated.", "success")
        return redirect(url_for('doctor_manage_availability'))

    return render_template('doctor_availability.html', doctor=doctor)


# ------------------------ PATIENT ROUTES ------------------------ #

@app.route('/patient')
@patient_required
def patient_dashboard():
    patient_id = session.get('patient_id')
    today = date.today()

    upcoming = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.date >= today
    ).order_by(Appointment.date, Appointment.start_time).all()

    past = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.date < today
    ).order_by(Appointment.date.desc(), Appointment.start_time.desc()).all()

    departments = Department.query.order_by(Department.name).all()

    return render_template(
        'patient_dashboard.html',
        user=session.get('user'),
        upcoming=upcoming,
        past=past,
        departments=departments
    )


@app.route('/patient/profile', methods=['GET', 'POST'])
@patient_required
def patient_profile():
    patient = Patient.query.get_or_404(session.get('patient_id'))

    today = date.today()

    past_appointments = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.date < today
    ).order_by(
        Appointment.date.desc(),
        Appointment.start_time.desc()
    ).all()

    if request.method == 'POST':
        patient.name = request.form.get('name')
        patient.email = request.form.get('email')
        patient.contact = request.form.get('contact')
        pw = request.form.get('password')
        if pw:
            patient.password = bcrypt.generate_password_hash(pw).decode('utf-8')
        db.session.commit()
        session['user'] = patient.name
        flash("Profile updated.", "success")
        return redirect(url_for('patient_profile'))

    return render_template('patient_profile.html', patient=patient, past_appointments=past_appointments)


@app.route('/patient/doctors')
@patient_required
def patient_search_doctors():
    q = request.args.get('q', '').strip()
    dept_id = request.args.get('dept_id')

    query = Doctor.query.join(Department).filter(Doctor.is_active == True)

    if q:
        query = query.filter(
            db.or_(
                Doctor.name.ilike(f"%{q}%"),
                Department.name.ilike(f"%{q}%")
            )
        )

    if dept_id:
        query = query.filter(Doctor.specialization_id == dept_id)

    doctors = query.order_by(Doctor.name).all()

    return render_template('patient_doctors.html', doctors=doctors, q=q)


@app.route('/patient/doctors/<int:doctor_id>/book', methods=['GET', 'POST'])
@patient_required
def patient_book_appointment(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    patient_id = session.get('patient_id')

    today = date.today()
    week_later = today + timedelta(days=7)

    # DB slots
    db_slots = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor_id,
        DoctorAvailability.date >= today,
        DoctorAvailability.date <= week_later,
        DoctorAvailability.is_available == True
    ).order_by(DoctorAvailability.date, DoctorAvailability.start_time).all()

    # already booked appointments
    booked = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date >= today,
        Appointment.date <= week_later,
        Appointment.status != 'Cancelled'
    ).all()

    booked_set = {(b.date, b.start_time, b.end_time) for b in booked}

    # build display slots with the fields your template expects
    display_slots = []
    for s in db_slots:
        is_booked = (s.date, s.start_time, s.end_time) in booked_set
        display_slots.append({
            "id": s.id,
            "weekday": s.date.strftime("%a"),            # Mon, Tue, ...
            "date_str": s.date.strftime("%Y-%m-%d"),     # 2025-11-16
            "start": s.start_time.strftime("%H:%M"),
            "end": s.end_time.strftime("%H:%M"),
            "is_booked": is_booked
        })

    if request.method == 'POST':
        slot_id = request.form.get('slot_id')
        selected = DoctorAvailability.query.get_or_404(slot_id)

        if (selected.date, selected.start_time, selected.end_time) in booked_set:
            flash("This slot is already booked. Please choose another.", "danger")
            return redirect(url_for('patient_book_appointment', doctor_id=doctor_id))

        appt = Appointment(
            doctor_id=doctor_id,
            patient_id=patient_id,
            date=selected.date,
            start_time=selected.start_time,
            end_time=selected.end_time,
            status='Booked'
        )
        db.session.add(appt)
        db.session.commit()
        flash("Appointment booked successfully!", "success")
        return redirect(url_for('patient_dashboard'))

    return render_template(
        'patient_book_appointment.html',
        doctor=doctor,
        slots=display_slots,   # <- use display_slots here
        booked_set=booked_set  # not strictly needed by template now
    )


@app.route('/patient/appointments/<int:appt_id>')
@patient_required
def patient_view_appointment(appt_id):
    patient_id = session.get('patient_id')
    appt = Appointment.query.get_or_404(appt_id)

    if appt.patient_id != patient_id:
        flash("You are not allowed to view this appointment.", "danger")
        return redirect(url_for('patient_dashboard'))

    return render_template('patient_appointment_detail.html', appt=appt)


@app.route('/patient/appointments/<int:appt_id>/cancel')
@patient_required
def patient_cancel_appointment(appt_id):
    patient_id = session.get('patient_id')
    appt = Appointment.query.get_or_404(appt_id)

    if appt.patient_id != patient_id:
        flash("You are not allowed to cancel this appointment.", "danger")
        return redirect(url_for('patient_dashboard'))

    if appt.status == 'Booked':
        appt.status = 'Cancelled'
        db.session.commit()
        flash("Appointment cancelled.", "info")
    else:
        flash("Only booked appointments can be cancelled.", "warning")

    return redirect(url_for('patient_dashboard'))

@app.route('/patient/appointments/<int:appt_id>/reschedule', methods=['GET', 'POST'])
@patient_required
def patient_reschedule_appointment(appt_id):
    patient_id = session.get('patient_id')
    appt = Appointment.query.get_or_404(appt_id)

    # safety: appointment must belong to this patient
    if appt.patient_id != patient_id:
        flash("You are not allowed to reschedule this appointment.", "danger")
        return redirect(url_for('patient_dashboard'))

    # Optional: only allow rescheduling of Booked appointments
    if appt.status != 'Booked':
        flash("Only booked appointments can be rescheduled.", "warning")
        return redirect(url_for('patient_dashboard'))

    doctor = appt.doctor
    today = date.today()
    week_later = today + timedelta(days=7)

    # All availability slots for the doctor in next 7 days
    base_slots = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor.id,
        DoctorAvailability.date >= today,
        DoctorAvailability.date <= week_later,
        DoctorAvailability.is_available == True
    ).order_by(DoctorAvailability.date, DoctorAvailability.start_time).all()

    # All other booked appointments of this doctor in the range
    other_appts = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date >= today,
        Appointment.date <= week_later,
        Appointment.status != 'Cancelled',
        Appointment.id != appt.id     # exclude the current appointment
    ).all()

    booked_set = {(b.date, b.start_time, b.end_time) for b in other_appts}

    # Build slot view objects like we did for booking
    slots = []
    for s in base_slots:
        is_booked = (s.date, s.start_time, s.end_time) in booked_set
        slots.append({
            "id": s.id,
            "weekday": s.date.strftime("%a"),
            "date_str": s.date.strftime("%Y-%m-%d"),
            "start": s.start_time.strftime("%H:%M"),
            "end": s.end_time.strftime("%H:%M"),
            "is_booked": is_booked
        })

    if request.method == 'POST':
        slot_id = request.form.get('slot_id')
        if not slot_id:
            flash("Please select a slot.", "warning")
            return redirect(url_for('patient_reschedule_appointment', appt_id=appt.id))

        selected = DoctorAvailability.query.get_or_404(slot_id)

        # double check not booked
        if (selected.date, selected.start_time, selected.end_time) in booked_set:
            flash("This slot is already booked. Please choose another.", "danger")
            return redirect(url_for('patient_reschedule_appointment', appt_id=appt.id))

        # update existing appointment
        appt.date = selected.date
        appt.start_time = selected.start_time
        appt.end_time = selected.end_time
        # keep status as 'Booked'
        db.session.commit()
        flash("Appointment rescheduled successfully!", "success")
        return redirect(url_for('patient_dashboard'))

    return render_template(
        'patient_reschedule_appointment.html',
        appt=appt,
        doctor=doctor,
        slots=slots
    )


# ------------------------ LOGOUT ------------------------ #

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
