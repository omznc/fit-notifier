import io
import json
import os
import time
import hashlib
from os import getenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote

import requests
from json_repair import loads as json_repair_loads
from bs4 import BeautifulSoup, Comment
from discord import Embed
from playwright.sync_api import sync_playwright
from unmarkd import unmark
from PIL import Image
import re

# Constants
WEBHOOK_URL = getenv('WEBHOOK_URL')
IMPORTANT_WEBHOOK_URL = getenv('IMPORTANT_WEBHOOK_URL')
DISCORD_BOT_TOKEN = getenv('DISCORD_BOT_TOKEN')
DISCORD_GUILD_ID = getenv('DISCORD_GUILD_ID')
DISCORD_ROLE_ID = getenv('DISCORD_ROLE_ID')
DISCORD_IMPORTANT_ROLE_ID = getenv('DISCORD_IMPORTANT_ROLE_ID')
FIT_USERNAME = getenv('FIT_USERNAME')
FIT_PASSWORD = getenv('FIT_PASSWORD')
IMGUR_CLIENT_ID = getenv('IMGUR_CLIENT_ID')
OPENROUTER_API_KEY = getenv('OPENROUTER_API_KEY')

INTERVAL = getenv('INTERVAL', 10)
STATE_DIR = getenv('STATE_DIR', '.')
FILE_NAME = os.path.join(STATE_DIR, 'latest.txt')
EVENTS_FILE = os.path.join(STATE_DIR, 'processed_events.json')
SEEN_LIMIT = int(getenv('SEEN_LIMIT', 200))
INITIAL_BACKFILL = int(getenv('INITIAL_BACKFILL', 1))
FORCE_BACKFILL = getenv('FORCE_BACKFILL', '').strip()
MARKER_FILE = os.path.join(STATE_DIR, 'backfill.done')
BASE_URL = 'https://www.fit.ba/student/'
POST_PREFIX = 'obavijesti/opsirnije.aspx'

AVATARS = {
    "Iris": "https://i.imgur.com/GGi41RP.jpg",
    "Senad": "https://i.imgur.com/5daub51.jpg",
    "Edina": "https://i.imgur.com/VSIBIdl.png",
    "Elmir": "https://i.imgur.com/OzejLET.png",
    "Denis": "https://i.imgur.com/tiqvWN8.png",
    "Indira": "https://i.imgur.com/B7NLccc.png",
    "Veldin": "https://i.imgur.com/kg6Q4qu.png",
    "Dubravka": "https://i.imgur.com/qSRAJCk.png",
    "Adil": "https://i.imgur.com/DvLFvle.jpg",
    "Nina": "https://i.imgur.com/HRdnmeR.png",
    "Sanja": "https://i.imgur.com/H3o1RCI.jpg",
    "Migdat": "https://i.imgur.com/qBUvYTN.jpg",
    "Lejla": "https://i.imgur.com/kxXOF5o.jpg",
    "Elvir": "https://i.imgur.com/SjSWx4y.jpg",
    "Haris": "https://i.imgur.com/DuWrvmU.png",
    "Mohamed": "https://i.imgur.com/ITsfzfi.png",
	"Goran": "https://i.imgur.com/iF9TdeP.png",
	"Dražena": "https://i.imgur.com/rsJebKA.png",
 	"Berun": "https://i.imgur.com/OLX4jOp.jpeg",
 	"Mabić": "https://i.imgur.com/NO54cZM.jpeg",
}
def login(page):
	print(f"Navigating to login page...")
	page.goto("https://www.fit.ba/student/login.aspx", timeout=60000)
	print(f"Page loaded: {page.url}")
	
	page.wait_for_selector('#txtBrojDosijea', timeout=10000)
	print(f"Typing username: {FIT_USERNAME[:4]}...")
	page.type('#txtBrojDosijea', FIT_USERNAME)
	print(f"Typing password...")
	page.type('#txtLozinka', FIT_PASSWORD)
	
	print(f"Taking pre-login screenshot...")
	page.screenshot(path='/tmp/before-login.png')
	
	print(f"Clicking login button...")
	page.click('#btnPrijava')
	
	print(f"Waiting for navigation...")
	time.sleep(3)
	print(f"Current URL after click: {page.url}")
	
	print(f"Taking post-login screenshot...")
	page.screenshot(path='/tmp/after-login.png')
	
	if page.url == 'https://www.fit.ba/student/login.aspx':
		error_elem = page.query_selector('#lblPoruka')
		if error_elem:
			error_msg = error_elem.text_content()
			print(f"Login error message: {error_msg}")
		print("Login failed - still on login page!")
		raise Exception("Login failed")
	
	print(f"Waiting for newslist...")
	try:
		page.wait_for_selector('ul.newslist', timeout=60000)
		print(f"Logged in! Current URL: {page.url}")
	except Exception as e:
		print(f"Error waiting for newslist: {e}")
		print(f"Current URL: {page.url}")
		print(f"Page title: {page.title()}")
		raise


class SessionExpired(Exception):
	pass


def normalize_href(href):
	href = str(href or '').strip()
	for prefix in ('https://www.fit.ba/student/', 'https://fit.ba/student/', 'http://www.fit.ba/student/', 'http://fit.ba/student/', '/student/', '/'):
		if href.startswith(prefix):
			href = href[len(prefix):]
			break
	return href


def load_seen():
	try:
		with open(FILE_NAME, 'r') as file:
			return [normalize_href(line) for line in file if line.strip()]
	except OSError:
		return []


def mark_seen(hrefs):
	seen = load_seen()
	for href in hrefs:
		href = normalize_href(href)
		if href not in seen:
			seen.append(href)
	seen = seen[-SEEN_LIMIT:]
	temp_name = FILE_NAME + '.tmp'
	with open(temp_name, 'w') as file:
		file.write('\n'.join(seen) + '\n')
	os.replace(temp_name, FILE_NAME)


# Scraping functions
def read_meta(node):
	link = node.find('a', id='lnkNaslov')
	author = node.find('a', id='HyperLink9')
	date = node.find('span', id='lblDatum')
	subject = node.find('span', id='lblPredmet')
	abstract = node.find('div', class_='abstract')
	return {
		'title': ' '.join(link.get_text().split()) if link else '',
		'date': date.get_text().strip() if date else '',
		'subject': subject.get_text().strip() if subject else '',
		'author': author.get_text().strip() if author else '',
		'email': (author.get('href') or '').replace('mailto:', '') if author else '',
		'abstract': abstract.get_text().strip() if abstract else ''
	}


def list_posts(page):
	print("Reloading news page...")
	page.goto(BASE_URL + 'default.aspx', timeout=60000)

	print("Getting page content...")
	soup = BeautifulSoup(page.content(), 'html.parser')

	ul = soup.find('ul', class_='newslist')
	if ul is None:
		raise SessionExpired(f'No newslist on {page.url}')

	# The news list carries the full metadata, but only for the newest post.
	featured = {}
	for item in ul.find_all('li') or [ul]:
		link = item.find('a', id='lnkNaslov')
		if link is not None and link.get('href'):
			featured[normalize_href(link.get('href'))] = read_meta(item)

	# The sidebar lists the recent posts, newest first.
	posts = []
	known = set()
	for link in soup.find_all('a'):
		href = normalize_href(link.get('href') or '')
		if not href.startswith(POST_PREFIX) or href in known:
			continue
		known.add(href)
		post = {
			'href': href,
			'title': ' '.join(link.get_text().split()),
			'date': '',
			'subject': '',
			'author': '',
			'email': '',
			'abstract': ''
		}
		post.update({key: value for key, value in featured.get(href, {}).items() if value})
		posts.append(post)
	return posts


def apply_force_backfill(page):
	if not FORCE_BACKFILL:
		return
	try:
		count = int(FORCE_BACKFILL)
	except ValueError:
		print(f'Ignoring invalid FORCE_BACKFILL: {FORCE_BACKFILL}')
		return
	if count <= 0:
		return
	try:
		with open(MARKER_FILE, 'r') as file:
			applied = file.read().strip()
	except OSError:
		applied = ''
	if applied == FORCE_BACKFILL:
		print(f'Backfill of {count} posts is already applied.')
		return

	posts = list_posts(page)
	older = [post['href'] for post in posts[count:]]
	with open(FILE_NAME, 'w') as file:
		file.write('\n'.join(reversed(older)) + ('\n' if older else ''))
	with open(MARKER_FILE, 'w') as file:
		file.write(FORCE_BACKFILL)
	print(f'Forced backfill: {min(count, len(posts))} newest posts are unseen, {len(older)} older posts are seen.')


def get_new_posts(page):
	posts = list_posts(page)
	print(f"Found {len(posts)} posts, newest: {posts[0]['href'] if posts else 'none'}")

	seen = load_seen()
	if seen or os.path.exists(FILE_NAME):
		new_posts = [post for post in posts if post['href'] not in seen]
	else:
		new_posts = posts[:INITIAL_BACKFILL]
		skipped = posts[INITIAL_BACKFILL:]
		if skipped:
			print(f'No state file. Marking {len(skipped)} older posts as seen.')
			mark_seen([post['href'] for post in reversed(skipped)])

	if not new_posts:
		print("No new post.")
	new_posts.reverse()
	return new_posts


def read_content(page):
	panel = BeautifulSoup(page.content(), 'html.parser').find('div', id='Panel1')
	if panel is None:
		return ''
	for node in panel.find_all(string=lambda text: isinstance(text, Comment)):
		node.extract()
	try:
		content = unmark(panel.prettify())
	except Exception as e:
		print(f'  Markdown conversion failed ({type(e).__name__}: {e}), using plain text')
		content = panel.get_text('\n')
	return re.sub(re.compile('<.*?>'), '', content)


def fetch_post_details(page, post):
	href = post['href']
	print(f"Navigating to post: {BASE_URL}{href}")
	page.goto(BASE_URL + href, timeout=60000)
	print("Waiting for Panel1...")
	page.wait_for_selector('#Panel1', timeout=30000)

	post = dict(post)
	meta = read_meta(BeautifulSoup(page.content(), 'html.parser'))
	for key, value in meta.items():
		if value and not post.get(key):
			post[key] = value
	if not post.get('author'):
		post['author'] = 'FIT'

	page.evaluate('''
			const panel = document.getElementById('Panel1');
			panel.style.position = 'fixed';
			panel.style.top = '0';
			panel.style.left = '0';
			panel.style.width = '100vw';
			panel.style.height = '100vh';
			panel.style.overflow = 'auto'; // Ensure the content scrolls if it's too large
			panel.style.zIndex = '9999'; // Overlay it over everything
			document.body.innerHTML = ''; // Remove all other content to focus on Panel1
			document.body.style.display = 'flex'; // Make the body a flex container
			document.body.style.flexDirection = 'column'; // Stack the content vertically
			document.body.style.justifyContent = 'center'; // Center the content
			document.body.style.alignItems = 'center'; // Center the content
			document.body.style.background = 'white';
			document.body.appendChild(panel); // Reattach Panel1 to the empty body
		''')

	try:
		screenshot = page.screenshot()
		rgba_image = Image.open(io.BytesIO(screenshot)).convert('RGBA')

		new_data = [
			(255, 255, 255, 0) if item[:3] == (255, 255, 255) else item
			for item in rgba_image.get_flattened_data()
		]
		rgba_image.putdata(new_data)

		transparent_bbox = rgba_image.getbbox()
		trimmed_image = rgba_image.crop(transparent_bbox)

		new_size = (trimmed_image.width + 100, trimmed_image.height + 100)
		image = Image.new("RGBA", new_size, (255, 255, 255, 255))
		image.paste(trimmed_image, (50, 50), trimmed_image)
	except Exception as e:
		print(f'  Screenshot failed, sending without the image: {e}')
		image = None

	return {**post, 'content': read_content(page), 'image': image}


EVENTS_JSON_SCHEMA = {
	'type': 'object',
	'properties': {
		'events': {
			'type': 'array',
			'items': {
				'type': 'object',
				'properties': {
					'type': {'type': 'string', 'description': 'exam, grade_entry, semester_validation, consultation, or other'},
					'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
					'time': {'type': 'string', 'description': 'HH:MM start time'},
					'end_time': {'type': 'string', 'description': 'HH:MM end time when range exists (e.g. 15:00 do 18:00)'},
					'title': {'type': 'string', 'description': 'Short event description'},
					'location': {'type': 'string', 'description': 'Room or location'},
					'subject': {'type': 'string', 'description': 'Course/subject name'}
				},
				'required': ['type', 'date', 'time', 'title', 'subject'],
				'additionalProperties': False
			}
		}
	},
	'required': ['events'],
	'additionalProperties': False
}

OPENROUTER_MODELS = [
	'dots-studio/dots-3-note-preview:free',
	'nex-agi/nex-n2.5-mini:free',
	'nvidia/nemotron-3-super-120b-a12b:free',
	'openrouter/free'
]

def extract_important_dates(details):
	if not OPENROUTER_API_KEY:
		print('  No OpenRouter API key, skipping date extraction')
		return []
	
	prompt = f"""Analiziraj sljedeću objavu i izvuci važne datume.

Post: "{details['title']}"
Sadržaj: "{details['content']}"
Datum objave: {details['date']}
Predmet: {details['subject']}

Traži: ispitne rokove, upis ocjena, ovjeru semestra, administrativne rokove.

Važno:
- Datum objave je {details['date']}, koristi kao referencu
- Objava koristi evropski format (DD.MM.YYYY), timezone Europe/Sarajevo
- U odgovoru datum uvijek pisi kao YYYY-MM-DD, a vrijeme kao HH:MM
- Ako postoji raspon (npr. "15:00h do 18:00h"), popuni time i end_time
- Ignoriši datume u prošlosti
- Ako nema važnih datuma, vrati praznu listu events"""

	payload = {
		'messages': [
			{'role': 'system', 'content': 'Ti si asistent koji ekstrahira važne datume iz fakultetskih objava.'},
			{'role': 'user', 'content': prompt}
		],
		'temperature': 0.1,
		'max_tokens': 2000,
		'reasoning': {'enabled': False},
		'response_format': {
			'type': 'json_schema',
			'json_schema': {
				'name': 'important_dates',
				'strict': True,
				'schema': EVENTS_JSON_SCHEMA
			}
		}
	}

	for model in OPENROUTER_MODELS:
		try:
			response = requests.post(
				'https://openrouter.ai/api/v1/chat/completions',
				headers={
					'Authorization': f'Bearer {OPENROUTER_API_KEY}',
					'Content-Type': 'application/json'
				},
				json={**payload, 'model': model},
				timeout=30
			)
			print(f'  OpenRouter {model}: {response.status_code}')
			if response.status_code not in (200, 201):
				print(f'    Error: {response.text[:150]}')
				continue
			result = response.json()
			choice = (result.get('choices') or [{}])[0]
			finish_reason = choice.get('finish_reason')
			content = (choice.get('message') or {}).get('content', '')
			if not content:
				print(f'    Empty response (finish_reason={finish_reason})')
				continue
			content = content.strip()
			if content.startswith('```'):
				content = content.split('```')[1]
				if content.startswith('json'):
					content = content[4:]
			content = content.strip()
			parsed = json_repair_loads(content) if content else {}
			events = parsed.get('events', []) if isinstance(parsed, dict) else []
			events = _validate_events(events, details)
			if not events and finish_reason == 'length':
				print(f'    Truncated response, trying next model')
				continue
			print(f'  Extracted {len(events)} valid events')
			return events
		except requests.RequestException as e:
			print(f'  {model} request failed: {e}')
			continue
		except Exception as e:
			print(f'  {model} failed: {e}')
			continue
	return []

DATE_FORMATS = ('%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d')

def _post_year(details):
	try:
		return datetime.strptime(str(details.get('date', ''))[:10], '%d.%m.%Y').year
	except (ValueError, TypeError):
		return datetime.now().year

def _normalize_date(value, details):
	raw = str(value or '').strip().rstrip('.')
	if not raw:
		return None
	try:
		return datetime.fromisoformat(raw).strftime('%Y-%m-%d')
	except ValueError:
		pass
	for fmt in DATE_FORMATS:
		try:
			return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
		except ValueError:
			continue
	for fmt in ('%d.%m', '%d/%m'):
		try:
			parsed = datetime.strptime(raw, fmt)
		except ValueError:
			continue
		return parsed.replace(year=_post_year(details)).strftime('%Y-%m-%d')
	return None

def _normalize_time(value, default='00:00'):
	raw = str(value or '').strip().lower()
	for suffix in ('sati', 'sat', 'h'):
		if raw.endswith(suffix):
			raw = raw[:-len(suffix)].strip()
			break
	raw = raw.replace('.', ':').replace(',', ':')
	if not raw:
		return default
	parts = raw.split(':')
	try:
		hour = int(parts[0])
		minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
	except ValueError:
		return default
	if not (0 <= hour <= 23 and 0 <= minute <= 59):
		return default
	return f'{hour:02d}:{minute:02d}'

def _validate_events(events, details):
	valid = []
	for i, e in enumerate(events if isinstance(events, list) else []):
		if not isinstance(e, dict):
			print(f'  Skipping invalid event {i}: not a dict')
			continue
		raw_date = e.get('date')
		date = _normalize_date(raw_date, details)
		title = e.get('title')
		if not title:
			print(f'  Skipping event {i}: missing title')
			continue
		if not date:
			print(f'  Skipping event {i}: invalid date {raw_date}')
			continue
		valid.append({
			'type': e.get('type', 'other'),
			'date': date,
			'time': _normalize_time(e.get('time')),
			'end_time': _normalize_time(e.get('end_time'), default=None),
			'title': str(title),
			'location': e.get('location') or 'Nije navedeno',
			'subject': e.get('subject') or details.get('subject', 'N/A')
		})
	return valid

def create_discord_event(event, details):
	if not DISCORD_BOT_TOKEN or not DISCORD_GUILD_ID:
		print('Missing Discord credentials for event creation')
		return None
	
	try:
		tz = ZoneInfo('Europe/Sarajevo')
		event_dt = datetime.strptime(f"{event['date']} {event.get('time', '00:00')}", '%Y-%m-%d %H:%M')
		event_dt = event_dt.replace(tzinfo=tz)
		end_time = event.get('end_time')
		if end_time:
			end_dt = datetime.strptime(f"{event['date']} {end_time}", '%Y-%m-%d %H:%M').replace(tzinfo=tz)
		else:
			end_dt = event_dt + timedelta(hours=2)
		if end_dt <= event_dt:
			end_dt = event_dt + timedelta(hours=2)
		
		now = datetime.now(tz)
		
		if event_dt < now:
			print(f'  Event in past, skipping: {event_dt}')
			return None
		
		if event_dt > now + timedelta(days=180):
			print(f'  Event too far in future, skipping: {event_dt}')
			return None
		
		payload = {
			'name': f"{event.get('subject', 'FIT')}: {event['title']}",
			'description': f"{details['content'][:500]}\n\nIzvor: https://www.fit.ba/student/{details['href']}\n\nAI generirano - može biti neispravno",
			'scheduled_start_time': event_dt.isoformat(),
			'scheduled_end_time': end_dt.isoformat(),
			'entity_type': 3,
			'entity_metadata': {
				'location': event.get('location', 'FIT Mostar')
			},
			'privacy_level': 2
		}
		
		response = requests.post(
			f'https://discord.com/api/v10/guilds/{DISCORD_GUILD_ID}/scheduled-events',
			headers={
				'Authorization': f'Bot {DISCORD_BOT_TOKEN}',
				'Content-Type': 'application/json'
			},
			json=payload,
			timeout=10
		)
		
		if response.status_code in (200, 201):
			event_data = response.json()
			event_url = f"https://discord.com/events/{DISCORD_GUILD_ID}/{event_data['id']}"
			print(f'  ✓ Discord event created: {event_url}')
			return event_url
		else:
			print(f'Discord API error creating event: {response.status_code}')
			print(f'Response: {response.text}')
	except Exception as e:
		print(f'Failed to create Discord event: {e}')
	
	return None

def _google_calendar_url(event, details):
	tz = ZoneInfo('Europe/Sarajevo')
	event_dt = datetime.strptime(f"{event['date']} {event.get('time', '00:00')}", '%Y-%m-%d %H:%M').replace(tzinfo=tz)
	end_time = event.get('end_time')
	if end_time:
		end_dt = datetime.strptime(f"{event['date']} {end_time}", '%Y-%m-%d %H:%M').replace(tzinfo=tz)
	else:
		end_dt = event_dt + timedelta(hours=2)
	start_str = event_dt.strftime('%Y%m%dT%H%M%S')
	end_str = end_dt.strftime('%Y%m%dT%H%M%S')
	params = {
		'action': 'TEMPLATE',
		'text': f"{event.get('subject', 'FIT')}: {event['title']}",
		'dates': f'{start_str}/{end_str}',
		'ctz': 'Europe/Sarajevo',
		'details': details['content'][:500] + f"\n\nhttps://www.fit.ba/student/{details['href']}",
		'location': event.get('location', '')
	}
	return 'https://calendar.google.com/calendar/render?' + '&'.join(f'{k}={quote(str(v))}' for k, v in params.items())

def send_important_date_webhook(event, details, event_url=None):
	if not IMPORTANT_WEBHOOK_URL:
		return
	
	type_emojis = {
		'exam': '📝',
		'grade_entry': '✅',
		'semester_validation': '📋',
		'consultation': '👨‍🏫',
		'other': '📌'
	}
	
	try:
		tz = ZoneInfo('Europe/Sarajevo')
		event_dt = datetime.strptime(f"{event['date']} {event.get('time', '00:00')}", '%Y-%m-%d %H:%M')
		event_dt = event_dt.replace(tzinfo=tz)
		timestamp = int(event_dt.timestamp())
		
		embed = Embed(
			title=f"{type_emojis.get(event['type'], '📌')} {event['title']}",
			color=0xff6b6b
		)
		embed.add_field(name='Termin', value=f'<t:{timestamp}:F> (<t:{timestamp}:R>)', inline=False)
		embed.add_field(name='Predmet', value=event.get('subject', 'N/A'), inline=False)
		embed.add_field(name='Lokacija', value=event.get('location', 'Nije navedeno'), inline=False)
		embed.add_field(name='Dodaj u kalendar', value=f'[Google Kalendar]({_google_calendar_url(event, details)})', inline=False)
		embed.add_field(name='Izvorni post', value=f'[Pogledaj objavu](https://www.fit.ba/student/{details["href"]})', inline=False)
		
		if event_url:
			embed.add_field(name='Discord događaj', value=f'[Dodano u kalendar servera]({event_url})', inline=False)
		
		embed.set_footer(text=f'Izvučeno iz objave: {details["title"]}\nAI generirano - može biti neispravno')
		
		author = details['author']
		avatar = AVATARS.get(author.split(' ')[0], f"https://ui-avatars.com/api/?name={author.replace(' ', '+')}")
		requests.post(
			IMPORTANT_WEBHOOK_URL,
			json={
				'embeds': [embed.to_dict()],
				'content': f'<@&{DISCORD_IMPORTANT_ROLE_ID}>' if DISCORD_IMPORTANT_ROLE_ID else '',
			'username': f'{author} (AI sažetak)',
				'avatar_url': avatar
			},
			headers={'Content-Type': 'application/json'},
			timeout=10
		)
	except Exception as e:
		print(f'Failed to send important date webhook: {e}')

def hash_event(event):
	event_str = f"{event.get('date', '')}-{event.get('time', '')}-{event.get('end_time', '')}-{event.get('title', '')}-{event.get('subject', '')}"
	return hashlib.md5(event_str.encode()).hexdigest()

def load_processed_events():
	try:
		with open(EVENTS_FILE, 'r') as f:
			return json.load(f)
	except:
		return {}

def save_processed_events(events):
	with open(EVENTS_FILE, 'w') as f:
		json.dump(events, f)

def process_important_dates(details):
	events = extract_important_dates(details)
	
	if not events:
		print('  No important dates found')
		return
	
	print(f'  Processing {len(events)} important dates')
	processed = load_processed_events()
	
	for event in events:
		event_hash = hash_event(event)
		if event_hash in processed:
			print(f'  Skipping already processed: {event.get("title", "?")}')
			continue
		
		print(f'  Found important date: {event.get("title", "?")} on {event.get("date")}')
		event_url = create_discord_event(event, details)
		send_important_date_webhook(event, details, event_url)
		
		processed[event_hash] = {
			'timestamp': datetime.now().isoformat(),
			'event': event
		}
	
	save_processed_events(processed)

# Function to send a Discord webhook with an embed
def send_webhook(details):
	embed = Embed(
		title=details['title'][:256],
		color=0x00ff00
	)
	try:
		timestamp = int(time.mktime(time.strptime(details["date"][:-2], "%d.%m.%Y %H:%M"))) - 7200
	except ValueError:
		timestamp = int(time.time())

	# content can have multiple empty newline gaps, have 1 at most
	details['content'] = '\n'.join([line for line in details['content'].split('\n') if line.strip() != ''])

	content_val = details['content'] if len(details['content']) <= 1024 else f'Predugo, [pogledaj kompletnu objavu](https://www.fit.ba/student/{details["href"]})'
	embed.add_field(name='Sadržaj', value=content_val or '\u200b', inline=False)
	embed.add_field(name='Email', value=(details['email'] or '\u200b')[:1024], inline=True)
	embed.add_field(name='Objavljeno', value=f'<t:{timestamp}:R>', inline=True)
	if details['subject'] != '':
		embed.add_field(name='Predmet', value=details['subject'][:1024], inline=False)
	embed.add_field(name='Link', value=f'[Klikni da otvoriš](https://www.fit.ba/student/{details["href"]})', inline=False)
	embed.set_footer(text='Source: github.com/omznc/fit-notifier')
 
	if details.get('image') is not None:
		with io.BytesIO() as image_binary:
			details['image'].save(image_binary, format='PNG')
			image_binary.seek(0)
			try:
				image_url = requests.post(
					'https://api.imgur.com/3/image',
					headers={'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'},
					files={'image': image_binary},
					timeout=30
				).json()['data']['link']
				embed.set_image(url=image_url)
			except Exception as e:
				print(f'Imgur upload failed, sending without the image: {e}')

	author = details['author'] or 'FIT'
	payload = {
		"embeds": [embed.to_dict()],
		"content": f"<@&{DISCORD_ROLE_ID}>" if DISCORD_ROLE_ID else '',
		"username": author,
		"avatar_url": AVATARS.get(author.split(' ')[0], "https://ui-avatars.com/api/?name=" + author.replace(' ', '+'))
	}
	last_error = ""
	for attempt in range(4):
		try:
			response = requests.post(WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
			if response.status_code == 204:
				print("Discord webhook sent successfully.")
				return True
			last_error = f"{response.status_code} {response.text[:500]}"
			if response.status_code not in (429, 500, 502, 503, 504):
				break
		except requests.RequestException as e:
			last_error = str(e)
		if attempt < 3:
			delay = 2 ** attempt
			print(f"Webhook attempt {attempt + 1} failed, retrying in {delay}s...")
			time.sleep(delay)
	print(f"Failed to send Discord webhook after 4 attempts: {last_error}")
	return False

	







if __name__ == "__main__":

	required_variables = [WEBHOOK_URL, FIT_USERNAME, FIT_PASSWORD, IMGUR_CLIENT_ID]
	missing_variables = [var for var in required_variables if var is None]
	if missing_variables:
		for var in missing_variables:
			print(f'{var} environment variable not set.')
		exit(1)

	if STATE_DIR != '.':
		os.makedirs(STATE_DIR, exist_ok=True)
	if os.path.isdir(FILE_NAME):
		os.rmdir(FILE_NAME)
	print(f'State directory: {os.path.abspath(STATE_DIR)} ({len(load_seen())} posts seen)')

	while True:
		try:
			with sync_playwright() as playwright:
				firefox = playwright.firefox
				browser = firefox.launch()
				context = browser.new_context()
				page = context.new_page()
				login(page)
				print("Logged in successfully. Starting to scrape...")
				apply_force_backfill(page)

				runs = 0
				while True:
					if runs == 60:
						print("Relogging...")
						break
					try:
						new_posts = get_new_posts(page)
					except SessionExpired as e:
						print(f"Session expired, relogging: {e}")
						break

					if new_posts:
						print(f'{len(new_posts)} new post(s) found!')

					for post in new_posts:
						try:
							details = fetch_post_details(page, post)
						except Exception as e:
							print(f'Failed to read post {post["href"]}: {e}')
							break
						if not send_webhook(details):
							print('Webhook failed. The post stays unseen and the next run retries it.')
							break
						mark_seen([post['href']])
						print('Checking for important dates...')
						try:
							process_important_dates(details)
						except Exception as e:
							print(f'Failed to process important dates: {e}')

					time.sleep(int(INTERVAL))
					runs += 1
		except Exception as e:
			print(f'Run failed, restarting the browser: {type(e).__name__}: {e}')
			time.sleep(int(INTERVAL))
