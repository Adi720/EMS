# EMS Seva — How to use the application

Each Sunday EMS is called an **EMS Congregation**, shown as e.g. *EMS Congregation (1/11/26)*.

## Once, at the start

**Types of user:** *System administrator* (created with `manage.py createsuperuser`; can do
everything, including Django Admin), *Coordinator* (runs Calling Seva), *Caller* (sees only
My calls). Saints never log in.

1. **Coordinators** — the system administrator creates them: Django Admin (menu under your
   name) → Users → Add user → username and password → Save → fill in the name, add the
   **Coordinator** group → Save. Leave Staff and Superuser unticked.
2. **Bring in the Saints and callers** — **Import** → **Upload workbook** (leave the optional
   boxes empty) → check the column mapping → **Validate rows**. On the review page:
   - **Create caller accounts**: callers in the workbook without an account are listed with a
     suggested username. Untick any that are just a different spelling of an existing person,
     then **Create ticked accounts**. The usernames and passwords are shown **once** — copy,
     print or download them and share each one privately.
   - Map any remaining caller names, and **Resolve** the rows marked *Needs resolution*
     (fix, link to an existing Saint, create new, or skip with a reason).
   - Enter the current 3-month cycle's name and start date, tick the confirmations,
     **Import now**. Only current Saints and their callers are imported — no old weekly history.
   - Or add Saints one by one: **Saints → Add Saint**, and callers in **Team → Add caller**.
3. Check **Assignments**: every caller has their list and "without a caller" is 0.

## Every week

| When | Who | What to do |
|---|---|---|
| Saturday morning | Coordinator | **Dashboard → Start calling for EMS Congregation (date)**. One click: it creates the coming Sunday, builds every caller's list from their contacts, and closes last week's calling. |
| Saturday | Callers | **My calls** → tap **📞 Call** → after the call tap one button: **Yes**, **Not Possible**, **Will Try** or **Call Not Connected**. Called again later? Just tap again — the latest answer counts. Use *Add notes or a call-back time* when needed. |
| During Saturday | Coordinator | **Dashboard** shows live progress per caller: completed, not yet attempted, Yes / Not Possible / Will Try / Unknown. |
| After Sunday | Coordinator | Open the congregation (*Details & exports*) → **Export** the summary or call list. Nothing else is required: next Saturday's click closes this week automatically. |

**Reminding callers**
- **WhatsApp (any time):** once calling is open, the dashboard shows **Share reminder on
  WhatsApp**. Tap it, choose your seva group and send. **Copy message** copies the same text
  for any other app.
- **Automatic email (optional):** if the system administrator has set it up, every Saturday
  morning the system starts calling by itself and emails each caller their link and how many
  contacts they have. Each caller is emailed once per congregation; callers need an email
  address on their user account (Django Admin → Users).

**Dark theme** — tap 🌙 / ☀️ in the top bar. Each person's choice is remembered on their device.

**What the numbers mean**
- *Completed* — at least one call attempt, whatever the outcome.
- *Connected* — the person answered (Yes, Not Possible or Will Try).
- *Will Try* is never counted as Yes.
- *Unknown* — not called yet, or the call did not connect.
- Yes + Not Possible + Will Try + Unknown always equals Assigned.

## When something changes

| Situation | What to do |
|---|---|
| New person collected at the stall | **Contacts → Add contact**, choose their caller. If calling is already open this week they appear in that caller's list straight away. |
| Contact away for a while | Open the contact → **Change status → Temporarily unavailable**, optional review date. They drop off the call lists but keep their caller; set them back to **Active** when they return. |
| Contact moved away | **Change status → Inactive / moved away**. Their caller allocation ends; all history is kept. |
| Person asks not to be called | **Change status → Do not call**. The phone number is hidden from callers and they are left out of exports. Reactivating needs a note confirming they agreed. |
| One contact should go to another caller | Open the contact → *Reassign to*, date, reason → **Save allocation**. |
| Caller leaves | **Allocations → Assign / move contacts → Move a caller's whole list** to someone else → Preview → Apply. |
| Every 3 months (rotation) | **Allocations → Swap lists** (caller A ↔ caller B) → Preview → Apply. Repeat for each pair. For several callers at once use *Advanced → Rotate among several callers*. |
| Extra or different congregation date | **Congregations → Add another date**, then **Start calling** on its page. |

In open congregations, calls not yet made move to the new caller; calls already made stay with
the original caller.

## Reports

- **Dashboard** — this week, by caller, plus previous congregations.
- **Congregations** — every week with its totals; open one for the full call list, per area, exports.
- **Monthly** — totals for a calendar month, by congregation and by caller; Excel/CSV export.
- **Audit** — who did what, and when.

## Callers — quick card

1. Log in → **My calls**.
2. *Pending* calls are at the top. Tap **📞 Call**.
3. Tap the result: **Yes** / **Not Possible** / **Will Try** / **Call Not Connected**.
4. Didn't connect? Try again later and tap the new result.
5. Callers only ever see their own contacts.
