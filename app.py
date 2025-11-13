from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Admin, Doctor, Patient, Department
from config import Config
from flask_bcrypt import Bcrypt

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

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html', user=session['user'])

@app.route('/doctor')
def doctor_dashboard():
    if session.get('role') != 'doctor':
        return redirect(url_for('login'))
    return render_template('doctor_dashboard.html', user=session['user'])

@app.route('/patient')
def patient_dashboard():
    if session.get('role') != 'patient':
        return redirect(url_for('login'))
    return render_template('patient_dashboard.html', user=session['user'])

@app.route('/add_doctor', methods=['GET', 'POST'])
def add_doctor():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        dept_id = request.form['department']
        password = bcrypt.generate_password_hash(request.form['password']).decode('utf-8')

        if Doctor.query.filter_by(email=email).first():
            flash("⚠️ Doctor with this email already exists.", "warning")
            return redirect(url_for('add_doctor'))

        doctor = Doctor(name=name, email=email, password=password, specialization_id=dept_id)
        db.session.add(doctor)
        db.session.commit()
        flash("✅ Doctor added successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    departments = Department.query.all()
    return render_template('add_doctor.html', departments=departments)


@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
