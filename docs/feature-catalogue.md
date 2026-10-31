# EMS Seva — Feature catalogue

What the application does, who uses each part, and where to find it.
Each Sunday EMS is called an **EMS Congregation**, shown as e.g. *EMS Congregation (1/11/26)*.
The people being called are **Saints**; the volunteers who phone them are **callers**.

**Manuals:** [Coordinator](coordinator-user-manual.md) · [Caller](caller-user-manual.md) ·
[System administrator](system-administrator-guide.md) · [Quick start](user-guide.md)

## Who uses what

| Role | Signs in to | Can do |
|---|---|---|
| **Caller** | My calls | See and call only their own Saints; record results |
| **Coordinator** | Dashboard | Everything for running Calling Seva: Saints, callers, assignments, calling, reports, import, audit |
| **System administrator** | Dashboard + Django Admin | Everything a coordinator can, plus creating coordinators and managing the server |

Saints never log in.

## Features

### Everyday calling
| Feature | Who | Where |
|---|---|---|
| One-click **Start calling** for the coming Sunday — builds every caller's list and closes last week | Coordinator | Dashboard, EMS Congregations |
| **My calls** phone screen: tap-to-call, four large result buttons, progress, filters (Pending, Done, Not connected, Call back) | Caller | My calls |
| Four results: **Yes**, **Not Possible**, **Will Try**, **Call Not Connected**; call again and tap again — the latest counts, all attempts are kept | Caller | My calls, call page |
| Optional note and **call-back time** on any call | Caller | Call page |
| **Share reminder on WhatsApp** / copy the reminder message | Coordinator | Dashboard |
| Optional automatic **Saturday reminder email** to every caller | System administrator sets it up | Server scheduled task |
| Live progress per caller, connected vs not connected, Yes / Not Possible / Will Try / Unknown | Coordinator | Dashboard, congregation page |
| Refresh call lists, close and reopen calling, add an extra date or venue | Coordinator | EMS Congregations |

### Saints
| Feature | Who | Where |
|---|---|---|
| **Saints Directory**: search by name or mobile, filter by area, caller and status, status tabs with counts | Coordinator | Saints |
| Add and edit Saints; mobile numbers checked (India +91 by default) | Coordinator | Saints |
| **Duplicate warning** when a mobile number is already used — never merged automatically | Coordinator | Add / edit Saint, import |
| Status: **Active**, **Temporarily unavailable** (with review date), **Inactive / moved away**, **Do not call** — with reason, date and full history | Coordinator | Saint page |
| Saint page with calls, caller history and status history timelines | Coordinator | Saint page |
| Export Saints to Excel or CSV (Do not call excluded unless chosen) | Coordinator | Saints → Export |
| **Delete Saints** added by mistake, one at a time or several selected, with confirmation and audit entry; Saints with call results are kept | Coordinator | Saint page, Saints → Delete selected |

### Team and assignments
| Feature | Who | Where |
|---|---|---|
| **Team**: add callers, edit details, reset passwords, deactivate / reactivate (history kept) | Coordinator | Team |
| Each Saint is looked after by **one caller for about three months** | Coordinator | Assignments |
| **Assign Saints**, **Move Saints** (whole list), **Swap caller lists**, rotate among several callers (Advanced) — always previewed before applying | Coordinator | Assignments |
| Warnings for Saints without a caller and when a three-month cycle is ending | Coordinator | Dashboard, Assignments |
| Full history: who had which Saint, from when, changed by whom and why | Coordinator | Saint page, Assignments → Recent changes |

### Import from Excel
| Feature | Who | Where |
|---|---|---|
| Four-step wizard: **Upload → Map columns → Review → Import**; nothing is saved until the last step | Coordinator | Import |
| Checks for missing details, invalid mobiles, duplicates, unmatched callers | Coordinator | Import → Review |
| **Create callers' logins from the workbook** with generated passwords, shown once to share | Coordinator | Import → Review |
| Fix, link or skip individual rows; repeat-safe (re-importing never duplicates) | Coordinator | Import → Review |
| Optional comparison with the "2026 Calling Sewa status" sheet | Coordinator | Import → Upload |

### Reports and records
| Feature | Who | Where |
|---|---|---|
| **Monthly report** by congregation and by caller, export to Excel / CSV | Coordinator | Monthly reports |
| Congregation results and call list export | Coordinator | Congregation page → Export |
| **Audit log** in plain language, filter by activity, person and date; cannot be edited | Coordinator | Audit log |

### Look, access and safety
| Feature | Notes |
|---|---|
| Light and dark theme | 🌙/☀️ button; remembered per device |
| Works on phones, tablets and computers | Callers' screens are designed for phones |
| Callers only ever see their own Saints | Checked on the server for every page |
| Login lock after 5 wrong passwords; sessions end after 2 hours idle | Unlock in Django Admin or by the administrator |
| Every change recorded | Audit log; passwords and phone numbers are never written to it |
| Spreadsheet exports protected against formula injection | Excel/CSV |

### How the numbers are counted
- **Assigned** — calls on the lists (withdrawn calls are not counted).
- **Completed** — at least one attempt, whatever the result.
- **Connected** — Yes, Not Possible or Will Try.
- **Unknown** — not called yet, or Call Not Connected.
- **Will Try is never counted as Yes.** Yes + Not Possible + Will Try + Unknown always equals Assigned.
- Actual attendance on Sunday is **not** tracked.

## Not included (yet)
- Recording who actually attended on Sunday.
- Sending WhatsApp or SMS messages automatically (the WhatsApp button opens WhatsApp with the message ready).
- Importing old weekly results from the workbook (only current Saints and their callers are imported).
