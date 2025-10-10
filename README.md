# Django ARMS (Airline Reservation Management System)

This repository contains a Django-based Airline Reservation Management System (ARMS).

# ✈️ Django ARMS - Airline Reservation Management System

<div align="center">

![Django](https://img.shields.io/badge/Django-4.0.3-092E20?style=for-the-badge&logo=django&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.0-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white)

*A comprehensive airline reservation management system built with Django*

[🚀 Live Demo](#) • [📖 Documentation](#features) • [🐛 Report Bug](https://github.com/praann07/django_arms/issues) • [💡 Request Feature](https://github.com/praann07/django_arms/issues)

</div>

---

## 🌟 Overview

Django ARMS is a full-featured **Airline Reservation Management System** designed to streamline flight bookings, manage airline operations, and provide an intuitive user experience for both passengers and administrators. Built with Django 4.0.3 and modern web technologies, it offers a robust solution for airline management needs.

## ✨ Key Features

### 🎫 **Passenger Experience**
- **Smart Flight Search** - Find flights by route, date, and preferences
- **Interactive Seat Selection** - Visual seat maps with real-time availability
- **Secure Reservations** - Multi-step booking process with confirmation
- **User Dashboard** - Manage bookings, view flight history, and notifications
- **Mobile-Responsive Design** - Seamless experience across all devices

### 🏢 **Admin Management**
- **Flight Scheduling** - Create recurring flight schedules with flexible patterns
- **Real-time Monitoring** - Track upcoming flights and occupancy rates
- **Reservation Management** - Approve, reject, and manage passenger bookings
- **Aircraft Management** - Maintain fleet information with capacity details
- **Airline & Airport Management** - Comprehensive airline and airport database

### 🔐 **Security & Authentication**
- **Custom User Profiles** - Extended user management with security questions
- **Password Recovery** - Secure password reset using security questions + DOB
- **Admin Middleware** - Role-based access control and user separation
- **Data Validation** - Comprehensive form validation and error handling

### 📊 **Advanced Features**
- **QR Code Integration** - Generate QR codes for reservations
- **CAPTCHA Security** - Bot protection for sensitive operations
- **Notification System** - Real-time notifications for booking updates
- **Data Import/Export** - CSV data management for bulk operations
- **Custom Template Tags** - Enhanced templating with currency formatting

## 🛠️ Technology Stack

| Category | Technology |
|----------|------------|
| **Backend** | Django 4.0.3, Python 3.8+ |
| **Database** | SQLite (Development), PostgreSQL-ready |
| **Frontend** | Bootstrap 5, jQuery, HTML5/CSS3 |
| **UI Components** | DataTables, Select2, Font Awesome |
| **Security** | Django Auth, CAPTCHA, Cryptography |
| **Additional** | Pillow (Image Processing), QR Code Generation |

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Git

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/praann07/django_arms.git
cd django_arms

## Quick setup (development)

1. Create a Python virtual environment and activate it:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set required environment variables (recommended, especially for production):

- `DJANGO_SECRET_KEY` (recommended as replacement for SECRET_KEY in settings)
- `ID_ENCRYPTION_KEY` (if using the encrypt template filter)

You can create a `.env` file locally with these keys (do NOT commit `.env`).

4. Run migrations and start the dev server:

```powershell
python manage.py migrate
python manage.py runserver
```

## Preparing to push to GitHub

1. Initialize a git repository (if not already):

```powershell
git init
git add .
git commit -m "Initial import of django_arms"
```

2. Add your GitHub remote and push:

```powershell
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

3. Share the repo URL with your teammates or create a zip and send it.

## Creating a zip for sharing (Windows PowerShell)

From project root (the repository root):

```powershell
Compress-Archive -Path * -DestinationPath ..\django_arms.zip -Force
```

This creates `django_arms.zip` on your Desktop (`..\` relative to the project folder). Teammates can extract and run the project locally.

## Notes & security

- `settings.py` currently contains a hard-coded `SECRET_KEY` and `DEBUG=True`. For production, move secrets to environment variables and set `DEBUG=False`.
- Add missing packages in `requirements.txt` if you use `qr_code`, `captcha`, or `cryptography`.

If you want, I can:
- Replace hard-coded SECRET_KEY with environment-based config and add `.env.example`.
- Update `requirements.txt` with missing packages.
- Initialize the local git repo and create the zip for you now.
