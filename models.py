from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# Admin
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Admin {self.username}>"


# Department / Specialization
class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationship: Department -> many Doctors
    doctors = db.relationship('Doctor', backref='department', lazy=True)

    def __repr__(self):
        return f"<Department {self.name}>"


# Doctor
class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    specialization_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    # availability: free-text (JSON string is acceptable here) OR use DoctorAvailability table below for structured slots
    availability = db.Column(db.String(500), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(20), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)   # blacklist / soft-delete
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)
    avail_slots = db.relationship('DoctorAvailability', backref='doctor', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Doctor {self.name} - {self.email}>"


# Patient
class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    contact = db.Column(db.String(20), nullable=True)
    password = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    appointments = db.relationship('Appointment', backref='patient', lazy=True)

    def __repr__(self):
        return f"<Patient {self.name} - {self.email}>"


# DoctorAvailability
# - Using this for precise availability checks and to show 7-day availability on patient dashboard.
class DoctorAvailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ensure simple uniqueness: a doctor should not have duplicate identical slots
    __table_args__ = (
        db.UniqueConstraint('doctor_id', 'date', 'start_time', 'end_time', name='uix_doc_slot'),
    )

    def __repr__(self):
        return f"<Avail Doctor:{self.doctor_id} {self.date} {self.start_time}-{self.end_time}>"

# Appointment
class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False, index=True)

    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    status = db.Column(db.String(20), default='Booked', nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # One-to-one: appointment -> treatment
    treatment = db.relationship('Treatment', backref='appointment', uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Appointment Dr:{self.doctor_id} Pt:{self.patient_id} {self.date} {self.start_time}>"

# Treatment 
class Treatment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False, unique=True)
    diagnosis = db.Column(db.Text, nullable=True)
    prescription = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Treatment appt:{self.appointment_id}>"
