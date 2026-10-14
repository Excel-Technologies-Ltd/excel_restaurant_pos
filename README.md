# Excel Restaurant POS (ArcPOS)

> Enterprise Omnichannel Restaurant Order, Billing, Kitchen Display (KDS), Table Management & Workforce Automation System built for **Frappe Framework v15** and **ERPNext**.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Framework](https://img.shields.io/badge/Frappe-v15-blue)](https://frappeframework.com)
[![Frontend](https://img.shields.io/badge/Frontend-React%2018%20%7C%20TypeScript%20%7C%20Vite-61dafb)](https://vitejs.dev)
[![Realtime](https://img.shields.io/badge/Realtime-Socket.IO%20%7C%20Redis-black)](https://socket.io)

---

## 📖 Complete Documentation

A comprehensive, production-grade technical manual covering architecture, data models, API references, security, and setup is available in **[DOCUMENTATION.md](./DOCUMENTATION.md)**.

### Specialized Guides in `/docs`:
- **[Order Anti-Spam & Turnstile Guide](./docs/order-antispam.md)** — Cloudflare Turnstile, honeypots, rate limiting, and idempotent checkout.
- **[Gift Cards Integration Guide](./docs/gift-card-frontend-integration-guide.md)** — Issuance, physical stock activation, and multi-card redemption.
- **[Employee Timeclock Backend & API](./docs/employee-timeclock-api.md)** — 6-digit PIN numpad authentication, shift cutoffs, and wage tracking.
- **[Item Search API](./docs/item-search-api.md)** — Typo-tolerant, ranked full-text fuzzy menu search.
- **[Order Receipt PDF API](./docs/order-receipt-pdf-api.md)** — Public receipt and delivery slip generation.
- **[Report SQL Stored Procedures](./docs/report-sql-procedures.md)** — MariaDB stored procedures architecture and auto-sync.
- **[Coupon Order Status Spec](./docs/coupon-order-status.md)** — Lifecycle bindings between Sales Invoices and promotional coupons.

---

## 🚀 Key Features

- **Omnichannel POS & Ordering:**
  - Modern React PWA Terminal (`/restaurant`).
  - QR-Code Collaborative Dine-In ordering (multi-diner cart with PII privacy masking).
  - Takeaway and Delivery integration with Uber Direct, DoorDash, and Uber Eats.
- **Kitchen & Back of House (KDS):**
  - Real-time station KDS with audible alarms and push notifications.
  - Automatic ERPNext Work Order & Stock Entry creation from recipe BOMs.
  - Wastage and scrap logging.
- **Floor Plan & Table Management:**
  - Interactive drag-and-drop table layout editor.
  - Live table status tracking (Available, Occupied, Reserved).
  - Table reservations with automated 24-hour reminder emails.
- **Financial & Payment Processing:**
  - Integrated Clover POS terminal sync.
  - Multi-tender payment tickets, tips, and split billing.
  - Automatic ERPNext Payment Entry posting and promotional discount journals.
  - Daily cash register opening/closing drawer audits.
- **Workforce Management:**
  - Encrypted 6-digit PIN attendance timeclock.
  - 04:00 AM business day cutoff logic.
  - Historical wage snapshotting and manager shift modifications.
- **Real-Time Communication:**
  - Standalone Socket.IO server on port 9001 with JWT Bearer Token validation.
  - Expo push notifications for Android/iOS mobile waiter and kitchen devices.

---

## 🛠️ Quick Start

### 1. Installation

```bash
# In your bench root directory
bench get-app excel_restaurant_pos
bench --site <site-name> install-app excel_restaurant_pos
bench --site <site-name> migrate
```

### 2. Building the Portal Frontend

```bash
cd apps/excel_restaurant_pos/portal
yarn install
yarn build
```

### 3. Running Services

```bash
bench start
```

Access the POS application at: `http://<your-site>:8000/restaurant`

---

## 📄 License

MIT © [Sohanur Rahman](mailto:sohan.dev@excelbd.com) & [Excel Technologies Ltd](https://excelbd.com)