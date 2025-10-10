
# Django ARMS (Airline Reservation Management System)
https://youtu.be/EJkb_slY4gU?si=LH_LaqsJEbSqSGjS 


**FIND THE PROJECT DEMO VIDEO IN THE ABOVE YOUTUBE LINK**
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

## 🏗️ Project Structure
django_arms/
├── armsApp/                    # Main application
│   ├── models/                 # Database models
│   ├── views/                  # View controllers
│   ├── templates/              # HTML templates
│   ├── static/                 # CSS, JS, Images
│   ├── management/commands/    # Custom Django commands
│   └── migrations/             # Database migrations
├── django_arms/                # Project settings
├── media/                      # User uploads
├── static/                     # Static files
└── requirements.txt            # Dependencies


## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Git
- Django
- SQL lyt
- Frontend(HTML,CS,JS)
- 

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/praann07/django_arms.git
cd django_arms

2.**Create virtual environment**
python -m venv venv
# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
3.**Install Dependencies**
pip install -r requirements.txt

4.**Database Setup**
python manage.py migrate
python manage.py collectstatic

5.**Run Development Server**
python manage.py runserver
**Visit http://127.0.0.1:8000 to see the application in action! 🎉**
