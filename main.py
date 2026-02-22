import io
import json
import time
import hashlib
from os import getenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote

import requests
from json_repair import loads as json_repair_loads
from bs4 import BeautifulSoup
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
LATEST_HREF = None
FILE_NAME = 'latest.txt'
EVENTS_FILE = 'processed_events.json'

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


# Scraping function to get the latest post details
def get_latest_post_details(page):
	print("Getting page content...")
	html = page.content()
	soup = BeautifulSoup(html, 'html.parser')

	print("Finding latest post...")
	ul = soup.find('ul', class_='newslist')
	href = ul.find('a', id='lnkNaslov').get('href')
	print(f"Found post: {href}")

	global LATEST_HREF
	if href == LATEST_HREF:
		print("No new post.")
		return None
	else:
		LATEST_HREF = href
		with open(FILE_NAME, 'w') as file:
			file.write(LATEST_HREF)

	print(f"Navigating to post: https://www.fit.ba/student/{href}")
	page.goto('https://www.fit.ba/student/' + href, timeout=60000)
	print("Waiting for Panel1...")
	page.wait_for_selector('#Panel1', timeout=30000)
 
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
	white_background = Image.new("RGBA", new_size, (255, 255, 255, 255))
	white_background.paste(trimmed_image, (50, 50), trimmed_image)

	content = page.content()
	content_soup = BeautifulSoup(content, 'html.parser')
	content = content_soup.find('div', id='Panel1')

	page.goto('https://www.fit.ba/student/default.aspx')

	content = unmark(content.prettify());

	cleanContent = re.compile('<.*?>');

	content = re.sub(cleanContent, '', content);
 
 
	return {
		'href': href,
		'title': ul.find('a', id='lnkNaslov').get_text(),
		'date': ul.find('span', id='lblDatum').get_text(),
		'subject': ul.find('span', id='lblPredmet').get_text(),
		'author': ul.find('a', id='HyperLink9').get_text(),
		'email': ul.find('a', id='HyperLink9').get('href').replace('mailto:', ''),
		'abstract': ul.find('div', class_='abstract').get_text().strip(),
		'content': content,
		'image': white_background
	}

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
	'arcee-ai/trinity-large-preview:free',
	'qwen/qwen3-4b:free',
	'nvidia/nemotron-nano-9b-v2:free',
	'arcee-ai/trinity-mini:free'
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
- Evropski format (DD.MM.YYYY), timezone Europe/Sarajevo
- Ako postoji raspon (npr. "15:00h do 18:00h"), popuni time i end_time
- Ignoriši datume u prošlosti
- Ako nema važnih datuma, vrati praznu listu events"""

	payload = {
		'messages': [
			{'role': 'system', 'content': 'Ti si asistent koji ekstrahira važne datume iz fakultetskih objava.'},
			{'role': 'user', 'content': prompt}
		],
		'temperature': 0.1,
		'max_tokens': 1000,
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
			content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
			if not content:
				print(f'    Empty response')
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
			print(f'  Extracted {len(events)} valid events')
			return events
		except requests.RequestException as e:
			print(f'  {model} request failed: {e}')
			continue
		except Exception as e:
			print(f'  {model} failed: {e}')
			continue
	return []

def _validate_events(events, details):
	valid = []
	for i, e in enumerate(events if isinstance(events, list) else []):
		if not isinstance(e, dict):
			print(f'  Skipping invalid event {i}: not a dict')
			continue
		date = e.get('date')
		title = e.get('title')
		if not date or not title:
			print(f'  Skipping event {i}: missing date or title')
			continue
		try:
			datetime.strptime(str(date), '%Y-%m-%d')
		except (ValueError, TypeError):
			print(f'  Skipping event {i}: invalid date {date}')
			continue
		valid.append({
			'type': e.get('type', 'other'),
			'date': str(date),
			'time': e.get('time') or '00:00',
			'end_time': e.get('end_time'),
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
		
		now = datetime.now(tz)
		
		if event_dt < now:
			print(f'  Event in past, skipping: {event_dt}')
			return None
		
		if event_dt > now + timedelta(days=180):
			print(f'  Event too far in future, skipping: {event_dt}')
			return None
		
		payload = {
			'name': f"{event.get('subject', 'FIT')}: {event['title']}",
			'description': f"{details['content'][:500]}\n\nIzvor: https://www.fit.ba/student/{details['href']}",
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
		embed.add_field(name='Dodaj u kalendar', value=f'[Google Calendar]({_google_calendar_url(event, details)})', inline=False)
		embed.add_field(name='Izvorni post', value=f'[Vidi objavu](https://www.fit.ba/student/{details["href"]})', inline=False)
		
		if event_url:
			embed.add_field(name='Discord Event', value=f'[Dodano u server kalendar]({event_url})', inline=False)
		
		embed.set_footer(text=f'Izvučeno iz objave: {details["title"]}')
		
		author = details['author']
		avatar = AVATARS.get(author.split(' ')[0], f"https://ui-avatars.com/api/?name={author.replace(' ', '+')}")
		requests.post(
			IMPORTANT_WEBHOOK_URL,
			json={
				'embeds': [embed.to_dict()],
				'content': f'<@&{DISCORD_IMPORTANT_ROLE_ID}>' if DISCORD_IMPORTANT_ROLE_ID else '',
				'username': f'{author} (AI Summary)',
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
	timestamp = int(time.mktime(time.strptime(details["date"][:-2], "%d.%m.%Y %H:%M"))) - 7200

	# content can have multiple empty newline gaps, have 1 at most
	details['content'] = '\n'.join([line for line in details['content'].split('\n') if line.strip() != ''])

	content_val = details['content'] if len(details['content']) <= 1024 else f'Too long, [view full post](https://www.fit.ba/student/{details["href"]})'
	embed.add_field(name='Content', value=content_val or '\u200b', inline=False)
	embed.add_field(name='Email', value=(details['email'] or '\u200b')[:1024], inline=True)
	embed.add_field(name='Posted', value=f'<t:{timestamp}:R>', inline=True)
	if details['subject'] != '':
		embed.add_field(name='Subject', value=details['subject'][:1024], inline=False)
	embed.add_field(name='Link', value=f'[Click here to open](https://www.fit.ba/student/{details["href"]})', inline=False)
	embed.set_footer(text='01101111 01101101 01111010 01101110 01100011')
 
	with io.BytesIO() as image_binary:
		details['image'].save(image_binary, format='PNG')  # Save as PNG
		image_binary.seek(0)  # Rewind the buffer to the beginning

        # Upload image to imgur
		image_url = requests.post(
            'https://api.imgur.com/3/image',
            headers={
                'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'
            },
            files={
                'image': image_binary
            }
        ).json()['data']['link']

        # Add the image URL to the embed
		embed.set_image(url=image_url)

		payload = {
			"embeds": [embed.to_dict()],
			"content": f"<@&{DISCORD_ROLE_ID}>" if DISCORD_ROLE_ID else '',
			"username": details['author'],
			"avatar_url": AVATARS.get(details['author'].split(' ')[0], "https://ui-avatars.com/api/?name=" + details['author'].replace(' ', '+'))
		}
		last_error = ""
		for attempt in range(4):
			try:
				response = requests.post(WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
				if response.status_code == 204:
					print("Discord webhook sent successfully.")
					return
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

	







if __name__ == "__main__":

	required_variables = [WEBHOOK_URL, FIT_USERNAME, FIT_PASSWORD, IMGUR_CLIENT_ID]
	missing_variables = [var for var in required_variables if var is None]
	if missing_variables:
		for var in missing_variables:
			print(f'{var} environment variable not set.')
		exit(1)
	import os

	if os.path.isdir(FILE_NAME):
		os.rmdir(FILE_NAME)
		LATEST_HREF = None
	elif not os.path.exists(FILE_NAME):
		LATEST_HREF = None
	else:
		with open(FILE_NAME, 'r') as f:
			LATEST_HREF = f.read().strip()

	while True:
		with sync_playwright() as playwright:
			firefox = playwright.firefox
			browser = firefox.launch()
			context = browser.new_context()
			page = context.new_page()
			login(page)
			print("Logged in successfully. Starting to scrape...")

			runs = 0
			while True:
				if runs == 60:
					print("Relogging...")
					break
				latest_post_details = get_latest_post_details(page)

				if latest_post_details is not None:
					print('New post found!')
					send_webhook(latest_post_details)
					print('Checking for important dates...')
					process_important_dates(latest_post_details)

				time.sleep(int(INTERVAL))
				runs += 1
		print("Logged in!")


