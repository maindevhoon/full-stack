CANTEEN PREORDER AND PICKUP SYSTEM
Full Stack Development Lab (24B15CS314)

SETUP
  Extract the submission ZIP. Open a terminal in the folder that contains
  manage.py. The project was verified with Python 3.13.

      python3 -m venv .venv
      source .venv/bin/activate
      python -m pip install -r requirements.txt
      python manage.py migrate
      python manage.py seed_demo
      python manage.py runserver

  On Windows, use py -m venv .venv and activate with
  .venv\Scripts\activate in Command Prompt. Then run the same python commands.

  Open http://127.0.0.1:8000/ in your browser. Bootstrap is bundled locally.

DEMO ACCOUNTS
  Student   student_demo    password: DemoStudent!2026
  Staff     staff_demo      password: DemoStaff!2026

  These accounts are for the local seeded demo database.

DEMONSTRATION
  1. Sign in as the student and add available menu items to the cart.
  2. Pick a slot with remaining capacity and place the order. Note its token.
  3. Sign in as staff in a separate browser session. Open the order queue.
  4. Move the order through Placed, Preparing, and Ready. Refresh the
     student's order page to see the current status.
  5. Enter the student's token on the staff page to mark the order Collected.
     Payment is made at pickup.
  6. Open the staff reports and check the collected order and sales amount.
     Use the date filter if needed.

TESTS
      python manage.py check
      python manage.py test

  The source ZIP contains migrations, demo seed data, application code,
  templates, static assets, tests, and the PDF report. The generated SQLite
  database is created locally by the setup commands.
