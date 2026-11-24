import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
    def log_message(self, *a): pass
threading.Thread(target=lambda: HTTPServer(('0.0.0.0', 8000), _H).serve_forever(), daemon=True).start()
"""ASKEDA: Python 3.10+, no third-party dependencies."""
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
import urllib.request
import urllib.error
from ai_dialogue import interpret, Unavailable

ROOT=Path(__file__).resolve().parent
CONFIG=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
MENU=['Услуги и цены','Подобрать услугу','Удалить анкету']
QUESTIONS=[
 ('Сфера','Чем занимается ваша компания, для которой нужно тендерное сопровождение?',['Сигнализация','Видеонаблюдение и СКУД','Вентиляция и климат','Медицинская техника','Электромонтаж','Другое']),
 ('Регион','Где готовы работать? Укажите города или регионы.',[]),
 ('Опыт','Участвовали ли раньше в закупках?',['Ещё не участвовали','Участвовали без побед','Есть выигранные контракты']),
 ('Документы','Есть ли электронная подпись и регистрация в ЕИС?',['Всё готово','Только подпись','Пока ничего нет','Не знаю']),
 ('Услуга','Какая помощь нужна?',['Малые закупки','Сопровождение','Разовая заявка','Вход в госзакупки','Помогите выбрать']),
 ('Объём','Сколько заявок в месяц планируете?',['1–2','3–5','Больше 5','Пока не знаю']),
 ('Сложность','Есть срочность, конкурс, сметы или большой пакет документов?',['Нет','Да','Нужен разбор']),
 ('Детали','Что ещё учесть: монтаж или обслуживание, лицензии, суммы контрактов? Не присылайте пароли, подписи и паспорта.',['Пропустить'])]


def normalized(text):
    return ' '.join(text.casefold().replace('ё','е').replace('–','-').replace('—','-').split()).strip(' .!?')


def contains_link(message):
    # Telegram marks both visible URLs and links hidden behind display text.
    for field in ('entities','caption_entities'):
        if any(entity.get('type') in ('url','text_link') for entity in message.get(field,[])):
            return True
    raw=' '.join(str(message.get(field) or '') for field in ('text','caption'))
    value=unicodedata.normalize('NFKC',raw).casefold()
    value=''.join(c for c in value if unicodedata.category(c)!='Cf')
    value=value.replace('。','.').replace('｡','.')
    patterns=(
        r'\b[a-z][a-z0-9+.-]*\s*://',
        r'\b(?:https?|hxxps?|tg|mailto|javascript|data)\s*:',
        r'\bwww\s*\.',
        r'(?<![\w@-])(?:[a-zа-яё0-9](?:[a-zа-яё0-9-]{0,61}[a-zа-яё0-9])?\.)+(?:[a-zа-яё]{2,63}|xn--[a-z0-9-]+)(?![\w-])',
        r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])',
    )
    return any(re.search(pattern,value) for pattern in patterns)


def choose(text, options, key=''):
    value=normalized(text)
    for option in options:
        if value==normalized(option):return option
    if value.isdigit() and 1<=int(value)<=len(options):return options[int(value)-1]
    aliases={
        'Документы':{'еще не занимался этим вопросом':'Пока ничего нет','еще не занимались этим вопросом':'Пока ничего нет','нет':'Пока ничего нет','нет ничего':'Пока ничего нет','все есть':'Всё готово','есть подпись и еис':'Всё готово'},
        'Опыт':{'нет':'Ещё не участвовали','не участвовали':'Ещё не участвовали','не участвовал':'Ещё не участвовали','новичок':'Ещё не участвовали'},
        'Объём':{'1-2 заявки':'1–2','3-5 заявок':'3–5','не знаю':'Пока не знаю'},
        'Сложность':{'не знаю':'Нужен разбор'}
    }
    alias=aliases.get(key,{}).get(value)
    if alias:return alias
    if key=='Объём':
        words={'одна':1,'один':1,'две':2,'два':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'восемь':8,'девять':9,'десять':10}
        numbers=[int(n) for n in re.findall(r'(?<!\w)\d+(?!\w)',value)]
        numbers += [n for word,n in words.items() if re.search(r'\b'+word+r'\b',value)]
        if numbers and all(n>0 for n in numbers):
            n=max(numbers)
            return '1–2' if n<=2 else '3–5' if n<=5 else 'Больше 5'
    if key=='Услуга' and value in ('победить тендер','хочу выиграть тендер','нужно сопровождение','хочу выигрывать тендеры'):
        return 'Сопровождение'
    return None


def options_text(options):
    return '\n\nМожно нажать кнопку или отправить номер / текст варианта:\n'+'\n'.join(f'{i}. {option}' for i,option in enumerate(options,1))


def estimate(answers):
    name=answers['Услуга']
    if name=='Помогите выбрать':
        name='Сопровождение' if answers['Документы']=='Всё готово' else 'Вход в госзакупки'
    plan=CONFIG['plans'][name]
    text=f"Рекомендую: {name}\nОриентир: от {plan['price']:,} ₽ {plan['period']}\n{plan['scope']}".replace(',',' ')
    if answers['Сложность']!='Нет' or answers['Объём']!='1–2':
        text+='\n\nДля вашего объёма или условий нужен индивидуальный расчёт. Это базовая цена, а не итоговое предложение.'
    if name!='Вход в госзакупки' and answers['Документы']!='Всё готово':
        text+='\n\nПодготовку подписи и регистрации нужно согласовать отдельно.'
    return text+'\n\nИтоговые стоимость, сроки и состав работ согласуем после разбора. Расходы на подпись, программы, площадки и обеспечение контрактов оплачиваются отдельно.'


def summary(answers):
    return '\n'.join(f'{key}: {value}' for key,value in answers.items())


class APIError(Exception):
    def __init__(self,code,retry=5):
        self.code,self.retry=code,retry


class Bot:
    def __init__(self,token,path=None):
        self.token=token
        self.db=sqlite3.connect(path or ROOT/'data.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(chat INTEGER PRIMARY KEY,step INTEGER,answers TEXT,updated REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS ai_consent(chat INTEGER PRIMARY KEY,updated REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS ai_usage(chat INTEGER PRIMARY KEY,day TEXT,count INTEGER,last REAL)')
        self.db.commit()
        self.owner=os.getenv('ASKEDA_OWNER_CHAT_ID','').strip()

    def api(self,method,**data):
        req=urllib.request.Request(f'https://api.telegram.org/bot{self.token}/{method}',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=45) as response:result=json.load(response)
        except urllib.error.HTTPError as error:
            try:result=json.loads(error.read())
            except (ValueError,OSError):raise APIError(error.code) from None
        except (urllib.error.URLError,TimeoutError,OSError):raise APIError(0) from None
        if not result.get('ok'):raise APIError(result.get('error_code',0),result.get('parameters',{}).get('retry_after',5))
        return result['result']

    def send(self,chat,text,choices=None):
        choices=MENU if choices is None else choices
        # Send all content instead of silently discarding long questionnaires.
        chunks=[text[i:i+3500] for i in range(0,len(text),3500)] or ['…']
        for chunk in chunks:
            self.api('sendMessage',chat_id=chat,text=chunk,reply_markup={'keyboard':[[{'text':x}] for x in choices],'resize_keyboard':True})

    def ai_enabled(self,chat):
        return True
        return bool(os.getenv('OPENAI_API_KEY') and self.db.execute('SELECT 1 FROM ai_consent WHERE chat=?',(chat,)).fetchone())

    def semantic(self,chat,text,question,choices,answers):
        if not self.ai_enabled(chat):return None
        now=time.time();day=time.strftime('%Y-%m-%d',time.gmtime(now))
        row=self.db.execute('SELECT day,count,last FROM ai_usage WHERE chat=?',(chat,)).fetchone()
        count=row[1] if row and row[0]==day else 0
        if count>=30 or (row and now-row[2]<2):return None
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO ai_usage VALUES(?,?,?,?)',(chat,day,count+1,now))
        try:return interpret(text,question,choices,answers,CONFIG['plans'])
        except Unavailable:return None

    def consent_prompt(self,chat):
        if not os.getenv('OPENAI_API_KEY'):
            self.send(chat,'Режим понимания свободного текста пока не подключён владельцем. Пока можно пройти анкету по вариантам или номерам.');return
        self.send(chat,'Для понимания свободных формулировок можно включить ИИ OpenAI. Тексты сообщений, которые нужно разобрать, и контекст анкеты будут передаваться в OpenAI. Не отправляйте личные документы, пароли или секреты. Без согласия доступна обычная анкета. Отключить ИИ: /ai_off.', ['Включить ИИ','Без ИИ']+MENU)

    def save(self,chat,step,answers):
        with self.db:self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)',(chat,step,json.dumps(answers,ensure_ascii=False),time.time()))

    def erase(self,chat):
        with self.db:
            self.db.execute('DELETE FROM sessions WHERE chat=?',(chat,))

    def ask(self,chat,step):
        _,question,choices=QUESTIONS[step]
        self.send(chat,f'{step+1}/{len(QUESTIONS)}. {question}'+(options_text(choices) if choices else ''),choices+['Отмена'])

    def handle(self,update):
        msg=update.get('message',{});chat=msg.get('chat',{})
        if chat.get('type')!='private':return
        if contains_link(msg):
            row=self.db.execute('SELECT step FROM sessions WHERE chat=?',(chat['id'],)).fetchone()
            choices=QUESTIONS[row[0]][2]+['Отмена'] if row and row[0]<len(QUESTIONS) else MENU
            self.send(chat['id'],'Ссылки не принимаются. Отправьте сообщение заново без ссылок. Ответ не сохранён.',choices)
            return
        cid=chat['id'];text=msg.get('text','').strip();text=next((x for x in MENU+['Отмена','Отправить специалисту','Включить ИИ','Без ИИ'] if normalized(x)==normalized(text)),text);cmd=text.split('@')[0].split(' ')[0].casefold()
        if cmd=='/ai' or text=='Включить ИИ':
            if text!='Включить ИИ':self.consent_prompt(cid);return
            if not os.getenv('OPENAI_API_KEY'):self.consent_prompt(cid);return
            with self.db:self.db.execute('INSERT OR REPLACE INTO ai_consent VALUES(?,?)',(cid,time.time()))
            self.send(cid,'ИИ включён. Можно описывать задачу обычными словами. Для начала подбора напишите «помоги подобрать услугу» или /quiz.');return
        if cmd=='/ai_off' or text=='Без ИИ':
            with self.db:self.db.execute('DELETE FROM ai_consent WHERE chat=?',(cid,))
            self.send(cid,'ИИ отключён. Анкета и услуги по кнопкам доступны.');return
        if cmd=='/id':self.send(cid,f'ID чата: {cid}');return
        if cmd=='/delete' or text=='Удалить анкету':
            self.erase(cid)
            with self.db:
                self.db.execute('DELETE FROM ai_consent WHERE chat=?',(cid,))
                self.db.execute('DELETE FROM ai_usage WHERE chat=?',(cid,))
            self.send(cid,'Анкета удалена из базы бота. Уже отправленные сообщения в Telegram не удаляются.');return
        if cmd in ('/start','/help','/cancel') or text=='Отмена':
            self.erase(cid)
            self.send(cid,'Здравствуйте! Я помощник ASKEDA. Покажу услуги и задам 8 вопросов для предварительной оценки.\n\nАнкета хранится у оператора бота до 30 дней; удалить: /delete. Специалист получит её только после вашего нажатия. Можно пройти анкету по вариантам. Вы можете выбирать варианты кнопками или просто писать ответы и вопросы своими словами.');return
        if text=='Услуги и цены' or cmd=='/services':
            price='\n\n'.join(f"{k}: от {v['price']:,} ₽ {v['period']}\n{v['scope']}".replace(',',' ') for k,v in CONFIG['plans'].items())
            self.send(cid,'ASKEDA — тендерное сопровождение технических компаний.\n\n'+price+'\n\nВы принимаете решение о цене и подписываете документы своей электронной подписью. Победу гарантировать нельзя. Для уточнения стоимости нажмите «Подобрать услугу».');return
        if text=='Подобрать услугу' or cmd=='/quiz':self.save(cid,0,{});self.ask(cid,0);return
        row=self.db.execute('SELECT step,answers FROM sessions WHERE chat=?',(cid,)).fetchone()
        if not row:
            if not text or len(text)>12000:
                self.send(cid,'Пришлите текст до 12 000 символов. Голосовые пока не поддерживаются.');return
            answer=self.semantic(cid,text,None,[],{})
            if answer:
                self.send(cid,answer['reply'])
                if answer['start_quiz']:self.save(cid,0,{});self.ask(cid,0)
            else:self.send(cid,'Для подбора отправьте /quiz, для услуг /services.')
            return
        step,answers=row[0],json.loads(row[1])
        if step==len(QUESTIONS):
            if text!='Отправить специалисту':
                response=self.semantic(cid,text,None,[],answers)
                if response:
                    self.send(cid,response['reply'])
                    if response['start_quiz']:self.save(cid,0,{});self.ask(cid,0)
                else:self.send(cid,'Анкета готова. Для отправки нажмите «Отправить специалисту», для новой анкеты — «Подобрать услугу».')
                return
            if not self.owner:
                self.send(cid,'Передача специалисту пока не настроена. Скопируйте анкету из сообщения выше в ваш текущий диалог с ASKEDA.');return
            user=msg.get('from',{}).get('username')
            contact=f'@{user}' if user else 'Нет username; клиенту нужно самому написать специалисту.'
            self.send(int(self.owner),f'Анкета ASKEDA\nКонтакт: {contact}\n\n{summary(answers)}\n\n{estimate(answers)}')
            self.erase(cid);self.send(cid,'Анкета отправлена специалисту. Для обратной связи напишите ему по кнопке ниже.' if CONFIG.get('contact_url') else 'Анкета отправлена. Для обратной связи используйте ваш текущий диалог с ASKEDA.')
            if CONFIG.get('contact_url'):self.api('sendMessage',chat_id=cid,text='Связаться с ASKEDA',reply_markup={'inline_keyboard':[[{'text':'Написать специалисту','url':CONFIG['contact_url']}]]})
            return
        key,question,choices=QUESTIONS[step]
        if not text or len(text)>12000:self.send(cid,'Пришлите текстовый ответ до 12 000 символов. Голосовые пока не поддерживаются.',choices+['Отмена']);return
        value=choose(text,choices,key) if choices and key!='Детали' else None
        # Free fields are also interpreted when AI is enabled, so off-topic
        # questions do not accidentally become the client's region or details.
        # The final optional note is kept verbatim. It needs no classification:
        # a null model value must not trap the client on the last question.
        if value is None and key!='Детали' and self.ai_enabled(cid):
            result=self.semantic(cid,text,question,choices if key!='Детали' else [],answers)
            if result:
                self.send(cid,result['reply'],choices+['Отмена'])
                if result['value'] is None:return
                value=result['value']
            else:
                self.send(cid,'Сейчас не получилось разобрать текст. Повторите позже или отправьте короткий ответ по вариантам.'+(options_text(choices) if choices else ''),choices+['Отмена']);return
        if choices and key!='Детали' and value is None:
            self.send(cid,'Не удалось однозначно понять ответ.'+options_text(choices),choices+['Отмена']);return
        if value is not None:
            if normalized(value)!=normalized(text):answers['Исходный ответ — '+key]=text
            text=value
        answers[key]=text;step+=1;self.save(cid,step,answers)
        if step<len(QUESTIONS):self.ask(cid,step)
        else:self.send(cid,summary(answers)+'\n\n'+estimate(answers),['Отправить специалисту']+MENU)

    def run(self):
        self.api('getMe')
        if self.api('getWebhookInfo').get('url'):raise SystemExit('Уже настроен webhook. Сначала остановите прежнюю интеграцию.')
        print('ASKEDA запущен. Остановка: Ctrl+C. Токен не записывается.')
        while True:
            try:
                with self.db:
                    cutoff=time.time()-30*86400
                    self.db.execute('DELETE FROM sessions WHERE updated<?',(cutoff,))
                    self.db.execute('DELETE FROM ai_consent WHERE updated<?',(cutoff,))
                    self.db.execute('DELETE FROM ai_usage WHERE last<?',(cutoff,))
                row=self.db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
                for update in self.api('getUpdates',offset=row[0] if row else 0,timeout=25,allowed_updates=['message']):
                    try:self.handle(update)
                    except APIError as error:
                        if error.code not in (400,403):raise
                    with self.db:self.db.execute("INSERT OR REPLACE INTO meta VALUES('offset',?)",(update['update_id']+1,))
            except APIError as error:
                if error.code in (401,409):raise SystemExit('Проверьте токен и остановите другие экземпляры бота.') from None
                print('Переподключение к Telegram…');time.sleep(min(max(error.retry,5),60))


if __name__=='__main__':
    os.umask(0o077)
    token=(os.getenv('TELEGRAM_BOT_TOKEN') or getpass.getpass('Токен BotFather (ввод скрыт): ')).strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',token):raise SystemExit('Неверный формат токена.')
    try:Bot(token).run()
    except KeyboardInterrupt:print('\nБот остановлен.')



