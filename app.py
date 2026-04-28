from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import datetime

app = Flask(__name__)
CORS(app)

DB_FILE = "volunteer.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS volunteers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT, email TEXT, phone TEXT,
                    skills TEXT, location TEXT, availability TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS needs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT, location TEXT, urgency TEXT,
                    posted_on TEXT, description TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    volunteer_id INTEGER, need_id INTEGER,
                    status TEXT, assigned_on TEXT,
                    FOREIGN KEY(volunteer_id) REFERENCES volunteers(id),
                    FOREIGN KEY(need_id) REFERENCES needs(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT, content TEXT, timestamp TEXT)''')

    # Seed initial data
    c.execute("SELECT COUNT(*) FROM needs")
    if c.fetchone()[0] == 0:
        seed_needs = [
            ('Food Distribution', 'Kovvur',     'High',   '2026-04-27', 'Urgent food supply needed.'),
            ('Medical Support',   'Nidadavole', 'High',   '2026-04-27', 'Medical camp required.'),
            ('Education',         'Vizag',      'Medium', '2026-04-27', 'Tutors needed for children.'),
        ]
        c.executemany("INSERT INTO needs (category, location, urgency, posted_on, description) VALUES (?, ?, ?, ?, ?)", seed_needs)

    conn.commit()
    conn.close()

# ── Matching Engine (CRITICAL FOR YOUR UI) ───────────────────
@app.route('/api/matching', methods=['GET'])
def get_matching_results():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Fetch all current needs
    c.execute("SELECT * FROM needs")
    needs = [dict(row) for row in c.fetchall()]
    
    final_matching = []
    
    for need in needs:
        # We look for volunteers whose skills are contained within the Need Category 
        # OR whose skill matches the category exactly.
        category_pattern = f"%{need['category']}%"
        
        c.execute("""
            SELECT name, email, phone, skills 
            FROM volunteers 
            WHERE LOWER(?) LIKE LOWER('%' || skills || '%') 
               OR LOWER(skills) LIKE LOWER(?)
        """, (need['category'], category_pattern))
        
        volunteers = [dict(row) for row in c.fetchall()]
        
        # Structure the data to match what your UI expects
        need_entry = {
            "id": need['id'],
            "category": need['category'],
            "location": need['location'],
            "urgency": need['urgency'],
            "posted_on": need['posted_on'],
            "description": need['description'],
            "matchedVolunteers": volunteers,
            "matchCount": len(volunteers)
        }
        final_matching.append(need_entry)
        
    conn.close()
    return jsonify(final_matching), 200

# ── Volunteers ───────────────────────────────────────────────
@app.route('/api/volunteers/register', methods=['POST'])
def register_volunteer():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id FROM volunteers WHERE email = ?", (data.get('email'),))
    if c.fetchone():
        conn.close()
        return jsonify({"message": "Email already registered."}), 400

    c.execute(
        "INSERT INTO volunteers (name, email, phone, skills, location, availability) VALUES (?, ?, ?, ?, ?, ?)",
        (data.get('name'), data.get('email'), data.get('phone'),
         data.get('skills'), data.get('location'), data.get('availability'))
    )
    vol_id = c.lastrowid

    # Immediate Matching Logic
    skill_val = data.get('skills', '').strip()
    c.execute("SELECT id FROM needs WHERE LOWER(category) LIKE LOWER(?)", (f"%{skill_val}%",))
    matched_needs = c.fetchall()
    
    for (n_id,) in matched_needs:
        c.execute("INSERT INTO assignments (volunteer_id, need_id, status, assigned_on) VALUES (?, ?, 'Pending', ?)",
                  (vol_id, n_id, datetime.date.today().isoformat()))

    conn.commit()
    conn.close()
    return jsonify({"message": "Registration successful", "volunteerId": vol_id}), 201

@app.route('/api/volunteers', methods=['GET'])
def get_volunteers():
    conn = get_db_connection()
    volunteers = [dict(row) for row in conn.execute("SELECT * FROM volunteers").fetchall()]
    conn.close()
    return jsonify(volunteers), 200

# ── Needs ────────────────────────────────────────────────────
@app.route('/api/needs', methods=['GET', 'POST'])
def handle_needs():
    conn = get_db_connection()
    if request.method == 'POST':
        data = request.json
        conn.execute("INSERT INTO needs (category, location, urgency, posted_on, description) VALUES (?, ?, ?, ?, ?)",
                     (data.get('category'), data.get('location'), data.get('urgency'), datetime.date.today().isoformat(), data.get('description')))
        conn.commit()
        conn.close()
        return jsonify({"message": "Need added"}), 201
    
    needs = [dict(row) for row in conn.execute("SELECT * FROM needs").fetchall()]
    conn.close()
    return jsonify(needs), 200

# ── Assignments ──────────────────────────────────────────────
@app.route('/api/assignments', methods=['GET'])
def get_assignments():
    conn = get_db_connection()
    query = '''SELECT a.id, v.name as volunteer, n.category as task, n.location, a.status, a.assigned_on
               FROM assignments a
               JOIN volunteers v ON a.volunteer_id = v.id
               JOIN needs n ON a.need_id = n.id ORDER BY a.id DESC'''
    assignments = [dict(row) for row in conn.execute(query).fetchall()]
    conn.close()
    return jsonify(assignments), 200

@app.route('/api/assignments/<int:assignment_id>', methods=['PATCH'])
def update_assignment(assignment_id):
    data = request.json
    conn = get_db_connection()
    conn.execute("UPDATE assignments SET status = ? WHERE id = ?", (data.get('status'), assignment_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"}), 200

# ── Stats & Messages ─────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db_connection()
    c = conn.cursor()
    stats = {
        "totalVolunteers": c.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0],
        "totalNeeds": c.execute("SELECT COUNT(*) FROM needs").fetchone()[0],
        "matchedAssignments": c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0],
        "completedTasks": c.execute("SELECT COUNT(*) FROM assignments WHERE status='Completed'").fetchone()[0]
    }
    conn.close()
    return jsonify(stats), 200

@app.route('/api/messages', methods=['GET', 'POST'])
def handle_messages():
    conn = get_db_connection()
    if request.method == 'POST':
        data = request.json
        conn.execute("INSERT INTO messages (sender, content, timestamp) VALUES (?, ?, ?)",
                     (data.get('sender', 'Anonymous'), data.get('content'), datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({"message": "Sent"}), 201
    
    msgs = [dict(row) for row in conn.execute("SELECT * FROM messages ORDER BY id DESC").fetchall()]
    conn.close()
    return jsonify(msgs), 200

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
