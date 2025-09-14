import telebot
import requests
import threading
import time
import os
from datetime import datetime, timedelta
from flask import Flask, request
from pymongo import MongoClient, ObjectId  # ObjectId সঠিকভাবে ইমপোর্ট

# Env variables
BOT_TOKEN = os.getenv('BOT_TOKEN', '8130807460:AAEtWSYLcyrKQdxLZT3u4npB-1KRIOSAaF4')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6094591421'))
GPLINKS_API_KEY = os.getenv('GPLINKS_API_KEY', 'c80cfdbc1d6d6173408a9baa53ce8ad0ed8ebe68')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'Enjoyvideo_bot')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb+srv://mrnahid8717_db_user:I5d9jPraCS58YCs9@cluster0.9lkdmju.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
DB_NAME = os.getenv('DB_NAME', 'telegram_bot_db')

# MongoDB Connection
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    client.server_info()  # Test connection
    db = client[DB_NAME]
    videos_collection = db['videos']
    user_access_collection = db['user_access']
    print("MongoDB connected successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# GPLinks URL Shorten
def shorten_with_gplinks(target_url):
    params = {'api': GPLINKS_API_KEY, 'url': target_url}
    try:
        response = requests.get('https://api.gplinks.com/api', params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return data['shortenedUrl']
    except Exception as e:
        print(f"GPLinks Error: {e}")
    return None

# Video Handler (Admin)
@bot.message_handler(content_types=['video'])
def handle_video(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "আপনার অ্যাডমিন অ্যাক্সেস নেই।")
        return
    
    file_id = message.video.file_id
    video_doc = {'file_id': file_id}
    inserted = videos_collection.insert_one(video_doc)
    video_id = str(inserted.inserted_id)
    
    link = f"https://t.me/{BOT_USERNAME}?start={video_id}"
    bot.reply_to(message, f"ভিডিও যোগ করা হয়েছে!\nচ্যানেলে পোস্ট করার লিংক: {link}")

# Start Command (User)
@bot.message_handler(commands=['start'])
def start_command(message):
    args = message.text.split()[1:]
    param = args[0] if args else None
    
    if not param:
        bot.reply_to(message, "ওয়েলকাম! চ্যানেল থেকে লিংক ক্লিক করুন।")
        return
    
    is_verified = '_verified' in param
    video_id_str = param.replace('_verified', '') if is_verified else param
    
    try:
        video_doc = videos_collection.find_one({'_id': ObjectId(video_id_str)})
        if not video_doc:
            bot.reply_to(message, "ভুল লিংক বা ভিডিও পাওয়া যায়নি।")
            return
    except Exception:
        bot.reply_to(message, "ভুল লিংক।")
        return
    
    user_id = message.from_user.id
    now = datetime.now()
    
    access_doc = user_access_collection.find_one({'user_id': user_id, 'video_id': video_id_str})
    needs_verify = True
    if access_doc and 'last_verify' in access_doc:
        last_verify = datetime.fromisoformat(access_doc['last_verify'])
        if now - last_verify < timedelta(hours=3):
            needs_verify = False
    
    if needs_verify and not is_verified:
        target_url = f"https://t.me/{BOT_USERNAME}?start={video_id_str}_verified"
        shorten_url = shorten_with_gplinks(target_url)
        if shorten_url:
            bot.reply_to(message, f"ভেরিফাই করুন (অ্যাড দেখুন): {shorten_url}\nদেখা শেষ হলে আবার বটে ফিরে আসুন।")
        else:
            bot.reply_to(message, "ভেরিফাই লিংক তৈরি করতে সমস্যা।")
    else:
        bot.send_video(message.chat.id, video_doc['file_id'])
        user_access_collection.update_one(
            {'user_id': user_id, 'video_id': video_id_str},
            {'$set': {'last_verify': now.isoformat()}},
            upsert=True
        )
        bot.reply_to(message, "ভিডিও পেয়েছেন! ৩ ঘণ্টা পর আবার ভেরিফাই করুন।")

# Delete Command (Admin)
@bot.message_handler(commands=['delete'])
def delete_access(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "অ্যাডমিন অ্যাক্সেস নেই।")
        return
    
    args = message.text.split()[1:]
    if len(args) < 1:
        bot.reply_to(message, "ব্যবহার: /delete USER_ID")
        return
    
    try:
        user_id = int(args[0])
        user_access_collection.delete_many({'user_id': user_id})
        bot.reply_to(message, f"ইউজার {user_id} এর অ্যাক্সেস ডিলিট করা হয়েছে।")
    except ValueError:
        bot.reply_to(message, "ভুল USER_ID।")

# Reminder Loop
def reminder_loop():
    while True:
        now = datetime.now()
        accesses = list(user_access_collection.find())
        for access in accesses:
            if 'last_verify' in access:
                last_verify = datetime.fromisoformat(access['last_verify'])
                if now - last_verify > timedelta(hours=3):
                    target_url = f"https://t.me/{BOT_USERNAME}?start={access['video_id']}_verified"
                    shorten_url = shorten_with_gplinks(target_url)
                    if shorten_url:
                        try:
                            bot.send_message(access['user_id'], f"৩ ঘণ্টা পার হয়েছে! আবার ভেরিফাই করুন: {shorten_url}")
                        except Exception as e:
                            print(f"Reminder error for {access['user_id']}: {e}")
        time.sleep(3600)  # 1 hour

# Webhook Handler for Render
@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode('utf-8'))
    bot.process_new_updates([update])
    return 'OK', 200

if __name__ == '__main__':
    print("বট চালু হচ্ছে...")
    webhook_url = f"https://{os.getenv('RENDER_APP_NAME', 'enjoy-video-hub')}.onrender.com/{BOT_TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    threading.Thread(target=reminder_loop, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
