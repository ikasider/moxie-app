# index.py
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Настройка путей для Vercel
base_dir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, '../templates'), 
            static_folder=os.path.join(base_dir, '../static'))

app.secret_key = os.environ.get('SECRET_KEY', '7eb0d50d0c5f7a80dc1c588dda823619df90d117421087b6')

# --- Настройка Базы Данных (Supabase / SQLite) ---
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # SQLAlchemy требует postgresql:// вместо postgres://
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace('postgres://', 'postgresql://')
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///moxie.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Папка для загрузок (на Vercel будет работать только временно)
# app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, '../static/uploads')
# os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ... далее идут твои модели (User, Post и т.д.) и роуты ...
# Добавили форматы видео
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}
db = SQLAlchemy(app)

def delete_old_file(filename):
    if filename and filename != 'default.png':
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except:
                pass

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_media(file, prefix="media"):
    if file and file.filename != '' and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    return None

# --- Модели Базы Данных ---
friendships = db.Table('friendships',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('friend_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.String(200), default="Привет, я в Moxie!")
    avatar = db.Column(db.String(120), default='default.png')
    gender = db.Column(db.String(20), nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    level = db.Column(db.Integer, default=1)
    xp = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # НОВОЕ ПОЛЕ: Приватность
    is_private = db.Column(db.Boolean, default=False)
    
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    ban_reason = db.Column(db.String(255), nullable=True)
    ban_until = db.Column(db.DateTime, nullable=True)

    posts = db.relationship('Post', backref='author', lazy=True, order_by="desc(Post.id)")
    friends = db.relationship('User', secondary=friendships,
                              primaryjoin=(friendships.c.user_id == id),
                              secondaryjoin=(friendships.c.friend_id == id),
                              backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')
    
    last_seen = db.Column(db.DateTime, default=datetime.now)
    def is_online(self):
        if self.last_seen:
            return datetime.now() < self.last_seen + timedelta(minutes=5)
        return False

    def is_friend(self, user): return self.friends.filter(friendships.c.friend_id == user.id).count() > 0
    def add_friend(self, user):
        if not self.is_friend(user): self.friends.append(user)
    def remove_friend(self, user):
        if self.is_friend(user): self.friends.remove(user)

    def is_following(self, user):
        return self.friends.filter(friendships.c.friend_id == user.id).count() > 0

    def is_followed_by(self, user):
        return user.friends.filter(friendships.c.friend_id == self.id).count() > 0

    def is_mutual(self, user):
        return self.is_following(user) and self.is_followed_by(user)

    def follow(self, user):
        if not self.is_following(user):
            self.friends.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.friends.remove(user)

    @property
    def following_count(self):
        return self.friends.count()

    @property
    def followers_count(self):
        return User.query.join(friendships, (friendships.c.user_id == User.id)).filter(friendships.c.friend_id == self.id).count()

    @property
    def mutual_friends_count(self):
        # Считаем только взаимных
        count = 0
        for f in self.friends:
            if f.is_following(self):
                count += 1
        return count

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=True)
    media = db.Column(db.Text, nullable=True) # ТЕПЕРЬ ТУТ TEXT (для хранения списка файлов через запятую)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=True)
    media = db.Column(db.Text, nullable=True) # ИЗМЕНЕНО НА TEXT (для 10 файлов)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

with app.app_context(): db.create_all()

@app.before_request
def check_banned():
    if request.endpoint in ['static', 'login', 'register', 'logout']:
        return
    user = get_current_user()
    if user and user.is_banned:
        # Проверяем, не истек ли временный бан
        if user.ban_until and datetime.now() > user.ban_until:
            user.is_banned = False
            user.ban_reason = None
            user.ban_until = None
            db.session.commit()
        else:
            return render_template('banned.html', user=user)

# Декоратор для защиты админских роутов
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user or not user.is_admin:
            flash('У вас нет прав администратора.', 'error')
            return redirect(url_for('feed'))
        return f(*args, **kwargs)
    return decorated_function

# --- Вспомогательные функции ---
def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

def add_xp(user, amount):
    user.xp += amount
    # Формула: Уровень = Корень из (XP / 50) + 1. 
    # Каждый новый уровень требует всё больше XP.
    new_level = int((user.xp / 50) ** 0.5) + 1
    user.level = min(100, new_level) # Ограничиваем 100-м уровнем
    db.session.commit()

@app.context_processor
def inject_user():
    return dict(user=get_current_user())

# --- Роуты (Авторизация) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует.')
            return redirect(url_for('register'))
        
        is_first_user = User.query.count() == 0
        new_user = User(username=username, password_hash=generate_password_hash(password), is_admin=is_first_user)
        db.session.add(new_user) # УБРАЛ ДУБЛИКАТ db.session.add
        db.session.commit()
        session['user_id'] = new_user.id
        return redirect(url_for('feed'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('feed'))
        flash('Неверное имя пользователя или пароль.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# --- Роуты (Основной функционал) ---
@app.route('/', methods=['GET'])
def feed():
    user = get_current_user()
    if not user: return redirect(url_for('login'))
    
    # Делаем JOIN таблиц и берем только посты тех, у кого is_banned == False
    posts = Post.query.join(User).filter(User.is_banned == False).order_by(Post.id.desc()).all()
    return render_template('feed.html', active_page='feed', posts=posts)

@app.route('/create_post', methods=['POST'])
def create_post():
    user = get_current_user()
    if not user: return redirect(url_for('login'))
    
    content = request.form.get('content')
    files = request.files.getlist('media') # Получаем список файлов
    
    saved_files = []
    # Ограничиваем до 10 файлов
    for file in files[:10]:
        filename = save_media(file, "post")
        if filename:
            saved_files.append(filename)
            
    media_str = ",".join(saved_files) if saved_files else None

    if content or media_str:
        new_post = Post(content=content, media=media_str, author=user)
        db.session.add(new_post)
        add_xp(user, 10)
        db.session.commit()
    
    return redirect(request.referrer or url_for('feed'))

@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    user = get_current_user()
    post = Post.query.get_or_404(post_id)
    if user and (post.user_id == user.id or user.is_admin):
        # Удаляем все картинки этого поста из папки uploads
        if post.media:
            for file in post.media.split(','):
                delete_old_file(file)
        db.session.delete(post)
        db.session.commit()
    return redirect(request.referrer)

@app.route('/edit_post/<int:post_id>', methods=['POST'])
def edit_post(post_id):
    user = get_current_user()
    post = Post.query.get_or_404(post_id)
    if user and post.user_id == user.id:
        post.content = request.form.get('content')
        db.session.commit()
    return redirect(request.referrer or url_for('feed'))

    # --- ДОБАВИТЬ РОУТ УДАЛЕНИЯ СООБЩЕНИЯ ---
@app.route('/delete_message/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    user = get_current_user()
    if not user: return redirect(url_for('login'))
    
    msg = Message.query.get_or_404(msg_id)
    # Удалить может только отправитель
    if msg.sender_id == user.id:
        # Если в сообщении были файлы — удаляем их из папки
        if msg.media:
            for file in msg.media.split(','):
                delete_old_file(file)
        db.session.delete(msg)
        db.session.commit()
    
    return redirect(request.referrer)

# --- Роут профиля (Теперь с функцией редактирования) ---
@app.route('/profile', defaults={'user_id': None}, methods=['GET', 'POST'])
@app.route('/profile/<int:user_id>', methods=['GET'])
def profile(user_id):
    current_user = get_current_user()
    if not current_user: return redirect(url_for('login'))
    
    # Обновляем статус онлайн
    current_user.last_seen = datetime.now()
    db.session.commit()

    target_user = User.query.get(user_id) if user_id else current_user
    if not target_user: return "Пользователь не найден", 404

    if request.method == 'POST' and not user_id:
        # 1. Текстовые данные
        current_user.username = request.form.get('username', current_user.username)
        current_user.bio = request.form.get('bio', '')
        current_user.gender = request.form.get('gender', '')
        current_user.is_private = 'is_private' in request.form
        
        # 2. Дата рождения
        bdate_str = request.form.get('birth_date')
        if bdate_str:
            try: current_user.birth_date = datetime.strptime(bdate_str, '%Y-%m-%d').date()
            except: pass

        # 3. Аватарка (с очисткой старой)
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename != '':
                new_avatar = save_media(file, "avatar")
                if new_avatar:
                    if current_user.avatar and current_user.avatar != 'default.png':
                        delete_old_file(current_user.avatar)
                    current_user.avatar = new_avatar

        db.session.commit()
        return redirect(url_for('profile'))

    # Расчет прогресса уровня
    # Расчет брал данные ТВОЕГО аккаунта
    # Теперь расчет берет данные того, чей это профиль
    xp_to_next = (target_user.level * 100) - target_user.xp
    progress = (target_user.xp / (target_user.level * 100)) * 100

    # Ограничиваем прогресс, чтобы он не был больше 100% или меньше 0%
    progress = max(0, min(100, progress)) 

    return render_template('profile.html', 
                           profile_user=target_user, 
                           user=current_user, 
                           progress=progress, 
                           xp_to_next=xp_to_next)

@app.route('/messenger', methods=['GET', 'POST'])
def messenger():
    user = get_current_user()
    if not user: return redirect(url_for('login'))

    chat_with_id = request.args.get('chat_with', type=int)
    chat_user = User.query.get(chat_with_id) if chat_with_id else None

    if request.method == 'POST' and chat_user:
        text = request.form.get('text', '')
        # Обработка до 10 файлов в сообщении!
        files = request.files.getlist('media')
        saved_files = []
        for file in files[:10]:
            filename = save_media(file, "msg")
            if filename: saved_files.append(filename)
            
        media_str = ",".join(saved_files) if saved_files else None

        if text or media_str:
            msg = Message(sender_id=user.id, receiver_id=chat_user.id, text=text, media=media_str)
            db.session.add(msg)
            add_xp(user, 2)
            db.session.commit()
        return redirect(url_for('messenger', chat_with=chat_user.id))

    # Вычисляем активные диалоги
    msg_users_ids = set()
    all_my_msgs = Message.query.filter((Message.sender_id == user.id) | (Message.receiver_id == user.id)).all()
    for m in all_my_msgs:
        if m.sender_id != user.id: msg_users_ids.add(m.sender_id)
        if m.receiver_id != user.id: msg_users_ids.add(m.receiver_id)
        
    active_users = User.query.filter(User.id.in_(msg_users_ids)).all()
    my_friends = user.friends.all() # Для поиска

    messages = []
    if chat_user:
        messages = Message.query.filter(
            ((Message.sender_id == user.id) & (Message.receiver_id == chat_user.id)) |
            ((Message.sender_id == chat_user.id) & (Message.receiver_id == user.id))
        ).order_by(Message.timestamp).all()

    return render_template('messenger.html', active_page='messenger', active_users=active_users, friends=my_friends, chat_user=chat_user, messages=messages)

@app.route('/settings')
def settings():
    if not get_current_user(): return redirect(url_for('login'))
    return render_template('settings.html', active_page='settings')

@app.route('/friends')
def friends_page():
    user = get_current_user()
    if not user: return redirect(url_for('login'))
    
    all_users = User.query.filter(User.id != user.id).all()
    my_friends = user.friends.all()
    
    # Отсеиваем тех, кто уже в друзьях, чтобы предложить их в блоке "Найти друзей"
    discover_users = [u for u in all_users if u not in my_friends]

    return render_template('friends.html', active_page='friends', my_friends=my_friends, discover_users=discover_users)

@app.route('/toggle_friend/<int:user_id>', methods=['POST'])
def toggle_friend(user_id):
    user = get_current_user()
    if not user: return redirect(url_for('login'))
    
    target = User.query.get_or_404(user_id)
    if target.id == user.id: return redirect(request.referrer)

    if user.is_following(target):
        user.unfollow(target)
    else:
        user.follow(target)
        add_xp(user, 5)

    db.session.commit()
    return redirect(request.referrer or url_for('friends_page'))





# --- РОУТЫ АДМИН-ПАНЕЛИ ---
@app.route('/admin')
@admin_required
def admin_panel():
    users = User.query.all()
    posts = Post.query.order_by(Post.id.desc()).all()
    return render_template('admin.html', active_page='admin', all_users=users, all_posts=posts)

@app.route('/admin/toggle_admin/<int:user_id>', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)
    
    # ИЕРАРХИЯ: Только Главный админ (ID 1) может назначать других админов
    if current_admin.id != 1:
        flash('Только владелец (ID 1) может управлять правами доступа.', 'error')
        return redirect(url_for('admin_panel'))

    if target_user.id != 1: # Нельзя снять админку с главного
        target_user.is_admin = not target_user.is_admin
        db.session.commit()
    return redirect(url_for('admin_panel'))

# --- Обновленный роут Ленты (скрывает посты забаненных) ---


# --- Обновленные роуты банов (умный редирект) ---
@app.route('/admin/ban/<int:user_id>', methods=['POST'])
@admin_required
def ban_user(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)
    
    # ИЕРАРХИЯ: 
    # 1. Нельзя забанить самого себя.
    # 2. Нельзя забанить Главного админа (ID 1).
    # 3. Обычный админ не может забанить другого админа.
    if target_user.id == 1:
        flash('Невозможно заблокировать владельца системы.', 'error')
        return redirect(request.referrer or url_for('admin_panel'))
    
    if target_user.is_admin and current_admin.id != 1:
        flash('Только владелец может блокировать других администраторов.', 'error')
        return redirect(request.referrer or url_for('admin_panel'))

    if target_user.id == current_admin.id:
        flash('Вы не можете заблокировать самого себя.', 'error')
        return redirect(request.referrer or url_for('admin_panel'))
        
    reason = request.form.get('reason', 'Нарушение правил сообщества')
    duration = request.form.get('duration')
    
    target_user.is_banned = True
    target_user.ban_reason = reason
    
    if duration and duration != 'perm':
        target_user.ban_until = datetime.now() + timedelta(days=int(duration))
    else:
        target_user.ban_until = None
        
    db.session.commit()
    return redirect(request.referrer or url_for('admin_panel'))

@app.route('/admin/unban/<int:user_id>', methods=['POST'])
@admin_required
def unban_user(user_id):
    target_user = User.query.get_or_404(user_id)
    target_user.is_banned = False
    target_user.ban_reason = None
    target_user.ban_until = None
    db.session.commit()
    return redirect(request.referrer or url_for('admin_panel'))

if __name__ == '__main__':
    app.run(debug=True)