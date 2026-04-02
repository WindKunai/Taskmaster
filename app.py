import os
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import case
import uuid
import glob
from anthropic import Anthropic
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.environ.get('SQLALCHEMY_TRACK_MODIFICATIONS')

db = SQLAlchemy(app)


CONVERSATIONS_DIR = os.path.join(os.path.dirname(__file__), 'conversations')
os.makedirs(CONVERSATIONS_DIR, exist_ok=True)
anthropic_client = Anthropic(api_key=os.environ.get("RANDOM_API"))

# ── Models ────────────────────────────────────────────────────────────────────

# Association table: many tasks <-> many categories
task_categories = db.Table(
    'task_categories',
    db.Column('task_id', db.Integer, db.ForeignKey('task.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True),
)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(7), nullable=False, default='#8a8680')  # hex

    def __repr__(self):
        return f'<Category {self.name}>'


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    due_date = db.Column(db.Date, nullable=True)

    task_list = db.relationship('TaskList', back_populates='task',
                                uselist=False, cascade='all, delete-orphan')
    categories = db.relationship('Category', secondary=task_categories,
                                 backref='tasks', lazy='subquery')

    def __repr__(self):
        return f'<Task {self.id}: {self.title}>'


class TaskList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False, unique=True)

    task = db.relationship('Task', back_populates='task_list')
    items = db.relationship('TaskListItem', back_populates='task_list',
                            order_by='TaskListItem.position',
                            cascade='all, delete-orphan')


class TaskListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey('task_list.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    text = db.Column(db.String(500), nullable=False)
    completed = db.Column(db.Boolean, default=False)

    task_list = db.relationship('TaskList', back_populates='items')


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_due_date(value: str):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def save_list_items(task, items_json: str):
    try:
        items = json.loads(items_json or '[]')
    except (ValueError, TypeError):
        items = []
    if not isinstance(items, list):
        return
    if task.task_list:
        db.session.delete(task.task_list)
        db.session.flush()
    if not items:
        return
    task_list = TaskList(task=task)
    db.session.add(task_list)
    for pos, item in enumerate(items):
        text = (item.get('text') or '').strip()
        if text:
            db.session.add(TaskListItem(
                task_list=task_list,
                position=pos,
                text=text,
                completed=bool(item.get('completed', False)),
            ))


def resolve_categories(cat_ids: list[str]) -> list[Category]:
    """Return Category objects for a list of id strings, ignoring invalid ones."""
    cats = []
    for cid in cat_ids:
        try:
            cat = db.session.get(Category, int(cid))
            if cat:
                cats.append(cat)
        except (ValueError, TypeError):
            pass
    return cats

# ── Conversation helpers ──────────────────────────────────────────────────────
 
def _conv_path(conv_id: str) -> str:
    return os.path.join(CONVERSATIONS_DIR, f"{conv_id}.json")
 
 
def load_conversation(conv_id: str) -> dict | None:
    path = _conv_path(conv_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
 
 
def save_conversation(conv: dict) -> None:
    with open(_conv_path(conv['id']), 'w', encoding='utf-8') as f:
        json.dump(conv, f, indent=2, ensure_ascii=False)
 
 
def list_conversations() -> list[dict]:
    files = glob.glob(os.path.join(CONVERSATIONS_DIR, '*.json'))
    convs = []
    for fp in files:
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                c = json.load(f)
            convs.append({
                'id': c['id'],
                'title': c.get('title', 'Untitled'),
                'created_at': c.get('created_at', ''),
                'updated_at': c.get('updated_at', ''),
                'message_count': len(c.get('messages', [])),
                'preview': next(
                    (m['content'][:80] for m in c.get('messages', []) if m['role'] == 'user'),
                    ''
                ),
            })
        except Exception:
            pass
    convs.sort(key=lambda x: x['updated_at'], reverse=True)
    return convs
 
 
def new_conversation(title: str = 'New conversation') -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conv = {
        'id': uuid.uuid4().hex,
        'title': title,
        'created_at': now,
        'updated_at': now,
        'messages': [],
    }
    save_conversation(conv)
    return conv


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    filter_by = request.args.get('filter', 'active')   # default: active
    sort_by = request.args.get('sort', 'due')           # default: due date
    cat_filter = request.args.get('cat', '')            # category id or ''

    query = Task.query
    if filter_by == 'active':
        query = query.filter_by(done=False)
    elif filter_by == 'done':
        query = query.filter_by(done=True)

    if cat_filter:
        try:
            query = query.filter(Task.categories.any(Category.id == int(cat_filter)))
        except (ValueError, TypeError):
            cat_filter = ''

    if sort_by == 'due':
        query = query.order_by(
            case((Task.due_date.is_(None), 1), else_=0),
            Task.due_date.asc()
        )
    elif sort_by == 'title':
        query = query.order_by(Task.title.asc())
    else:
        query = query.order_by(Task.created_at.desc())

    tasks = query.all()
    total = Task.query.count()
    done_count = Task.query.filter_by(done=True).count()
    today = date.today()

    month_start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    month_count = Task.query.filter(
        Task.done == True,
        Task.created_at >= month_start,
    ).count()

    overdue_count = Task.query.filter(
        Task.done == False,
        Task.due_date < today,
        Task.due_date.isnot(None),
    ).count()

    all_categories = Category.query.order_by(Category.name).all()

    return render_template('index.html', tasks=tasks, filter_by=filter_by,
                           sort_by=sort_by, cat_filter=cat_filter,
                           total=total, done_count=done_count,
                           today=today, month_count=month_count,
                           overdue_count=overdue_count,
                           all_categories=all_categories)


@app.route('/add', methods=['GET', 'POST'])
def add_task():
    all_categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')
        if not title:
            flash('Task title is required.', 'error')
            return render_template('add_task.html', all_categories=all_categories)
        task = Task(
            title=title,
            description=description if content_type == 'text' else '',
            due_date=parse_due_date(request.form.get('due_date')),
        )
        task.categories = resolve_categories(request.form.getlist('categories'))
        db.session.add(task)
        db.session.flush()
        if content_type == 'list':
            save_list_items(task, request.form.get('list_items', '[]'))
        db.session.commit()
        flash('Task added.', 'success')
        return redirect(url_for('index'))
    return render_template('add_task.html', all_categories=all_categories)


@app.route('/edit/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    task = db.get_or_404(Task, task_id)
    all_categories = Category.query.order_by(Category.name).all()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        content_type = request.form.get('content_type', 'text')
        if not title:
            flash('Task title is required.', 'error')
            return render_template('edit_task.html', task=task, all_categories=all_categories)
        task.title = title
        task.due_date = parse_due_date(request.form.get('due_date'))
        task.categories = resolve_categories(request.form.getlist('categories'))
        if content_type == 'text':
            task.description = description
            if task.task_list:
                db.session.delete(task.task_list)
        else:
            task.description = ''
            save_list_items(task, request.form.get('list_items', '[]'))
        db.session.commit()
        flash('Task updated.', 'success')
        return redirect(url_for('index'))
    return render_template('edit_task.html', task=task, all_categories=all_categories)


@app.route('/toggle/<int:task_id>', methods=['POST'])
def toggle_task(task_id):
    task = db.get_or_404(Task, task_id)
    task.done = not task.done
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/toggle_item/<int:item_id>', methods=['POST'])
def toggle_item(item_id):
    item = db.get_or_404(TaskListItem, item_id)
    item.completed = not item.completed
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/remove_due_date/<int:task_id>', methods=['POST'])
def remove_due_date(task_id):
    task = db.get_or_404(Task, task_id)
    task.due_date = None
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    task = db.get_or_404(Task, task_id)
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('index'))

@app.route('/chat')
def chat_index():
    convs = list_conversations()
    return render_template('chat.html', conversations=convs, active_conv=None)
 
 
@app.route('/chat/new', methods=['POST'])
def chat_new():
    title = request.form.get('title', '').strip() or 'New conversation'
    conv = new_conversation(title)
    return redirect(url_for('chat_open', conv_id=conv['id']))
 
 
@app.route('/chat/<conv_id>')
def chat_open(conv_id):
    conv = load_conversation(conv_id)
    if conv is None:
        flash('Conversation not found.', 'error')
        return redirect(url_for('chat_index'))
    convs = list_conversations()
    return render_template('chat.html', conversations=convs, active_conv=conv)
 
 
@app.route('/chat/<conv_id>/send', methods=['POST'])
def chat_send(conv_id):
    conv = load_conversation(conv_id)
    if conv is None:
        return {'error': 'Conversation not found'}, 404
 
    user_text = (request.json or {}).get('message', '').strip()
    if not user_text:
        return {'error': 'Empty message'}, 400
 
    now = datetime.now(timezone.utc).isoformat()
    conv['messages'].append({'role': 'user', 'content': user_text, 'ts': now})
 
    # Auto-title from first user message
    if len(conv['messages']) == 1:
        conv['title'] = user_text[:60] + ('…' if len(user_text) > 60 else '')
 
    # Build Anthropic message history (role + content only)
    history = [{'role': m['role'], 'content': m['content']} for m in conv['messages']]
 
    try:
        response = anthropic_client.messages.create(
            model='claude-opus-4-6',
            max_tokens=2048,
            messages=history,
        )
        assistant_text = response.content[0].text
    except Exception as e:
        return {'error': str(e)}, 500
 
    conv['messages'].append({'role': 'assistant', 'content': assistant_text, 'ts': now})
    conv['updated_at'] = now
    save_conversation(conv)
 
    return {
        'reply': assistant_text,
        'title': conv['title'],
        'conv_id': conv_id,
    }
 
 
@app.route('/chat/<conv_id>/rename', methods=['POST'])
def chat_rename(conv_id):
    conv = load_conversation(conv_id)
    if conv is None:
        return {'error': 'Not found'}, 404
    new_title = (request.json or {}).get('title', '').strip()
    if new_title:
        conv['title'] = new_title[:80]
        save_conversation(conv)
    return {'title': conv['title']}
 
 
@app.route('/chat/<conv_id>/delete', methods=['POST'])
def chat_delete(conv_id):
    path = _conv_path(conv_id)
    if os.path.exists(path):
        os.remove(path)
    flash('Conversation deleted.', 'success')
    return redirect(url_for('chat_index'))
 
 
@app.route('/chat/usage')
def chat_usage():
    from flask import jsonify
    days = max(1, min(30, int(request.args.get('days', 1))))
 
    # Requires ANTHROPIC_ADMIN_KEY in .env — separate from your regular API key
    admin_key = os.environ.get('ANTHROPIC_ADMIN_KEY')
    if not admin_key:
        return jsonify({'error': 'ANTHROPIC_ADMIN_KEY not set in .env'}), 500
 
    from anthropic import Anthropic as AdminClient
    admin = AdminClient(api_key=admin_key)
 
    starting = datetime.now(timezone.utc) - timedelta(days=days)
    starting = starting.replace(hour=0, minute=0, second=0, microsecond=0)
 
    try:
        report = admin.admin.cost_report.retrieve(
            starting_at=starting.isoformat(),
            bucket_width='1d',
            group_by=['description'],
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500
 
    buckets = []
    for bucket in report.data:
        results = []
        bucket_total = 0.0
        for item in bucket.results:
            amt = float(item.amount or '0')
            bucket_total += amt
            results.append({
                'amount':     item.amount,
                'cost_type':  item.cost_type,
                'model':      item.model,
                'token_type': item.token_type,
                'currency':   item.currency,
            })
        buckets.append({
            'starting_at': bucket.starting_at,
            'ending_at':   bucket.ending_at,
            'results':     results,
            'total':       bucket_total,
        })
 
    return jsonify({'buckets': buckets, 'days': days})

# ── Category management ───────────────────────────────────────────────────────

@app.route('/categories', methods=['GET', 'POST'])
def manage_categories():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            color = request.form.get('color', '#8a8680').strip()
            if name:
                if Category.query.filter_by(name=name).first():
                    flash('Category already exists.', 'error')
                else:
                    db.session.add(Category(name=name, color=color))
                    db.session.commit()
                    flash(f'Category "{name}" added.', 'success')
            else:
                flash('Category name is required.', 'error')
        elif action == 'delete':
            cat_id = request.form.get('cat_id')
            cat = db.get_or_404(Category, cat_id)
            db.session.delete(cat)
            db.session.commit()
            flash(f'Category "{cat.name}" deleted.', 'success')
        return redirect(url_for('manage_categories'))
    categories = Category.query.order_by(Category.name).all()
    return render_template('categories.html', categories=categories)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
    # app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
