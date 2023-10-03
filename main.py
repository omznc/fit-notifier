import time
from os import getenv

import requests
from bs4 import BeautifulSoup
from discord import Embed
from playwright.sync_api import sync_playwright
from unmarkd import unmark

# Constants
WEBHOOK_URL = getenv('WEBHOOK_URL')
USERNAME = getenv('USERNAME')
PASSWORD = getenv('PASSWORD')
INTERVAL = getenv('INTERVAL', 10)
LATEST_HREF = None
FILE_NAME = 'latest.txt'

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
}
def login(page):
	page.goto("https://www.fit.ba/student/login.aspx")
	page.type('#txtBrojDosijea', USERNAME)
	page.type('#txtLozinka', PASSWORD)
	page.click('#btnPrijava')
	page.wait_for_url('https://www.fit.ba/student/default.aspx')


# Scraping function to get the latest post details
def get_latest_post_details(page):
	html = page.content()
	soup = BeautifulSoup(html, 'html.parser')

	# Find the latest post details
	ul = soup.find('ul', class_='newslist')
	href = ul.find('a', id='lnkNaslov').get('href')

	global LATEST_HREF
	if href == LATEST_HREF:
		return None
	else:
		LATEST_HREF = href
		with open(FILE_NAME, 'w') as file:
			file.write(LATEST_HREF)

	page.goto('https://www.fit.ba/student/' + href)
	page.wait_for_selector('#Panel1')
	content = page.content()
	content_soup = BeautifulSoup(content, 'html.parser')
	content = content_soup.find('div', id='Panel1')

	page.goto('https://www.fit.ba/student/default.aspx')

	return {
		'href': href,
		'title': ul.find('a', id='lnkNaslov').get_text(),
		'date': ul.find('span', id='lblDatum').get_text(),
		'subject': ul.find('span', id='lblPredmet').get_text(),
		'author': ul.find('a', id='HyperLink9').get_text(),
		'email': ul.find('a', id='HyperLink9').get('href').replace('mailto:', ''),
		'abstract': ul.find('div', class_='abstract').get_text().strip(),
		'content': unmark(content.prettify())
	}

# Function to send a Discord webhook with an embed
def send_webhook(details):
	embed = Embed(
		title=details['title'],
		description=details['abstract'],
		color=0x00ff00
	)
	timestamp = int(time.mktime(time.strptime(details["date"][:-2], "%d.%m.%Y %H:%M"))) - 7200

	# content can have multiple empty newline gaps, have 1 at most
	details['content'] = '\n'.join([line for line in details['content'].split('\n') if line.strip() != ''])

	if len(details['content']) < 2000:
		embed.add_field(name='Content', value=details['content'], inline=False)
	else:
		embed.add_field(name='Content',
		                value=f'Too long, click [here](https://www.fit.ba/student/{details["href"]}) to view the full post.',
		                inline=False)

	embed.add_field(name='Author', value=details['author'], inline=True)
	embed.add_field(name='Email', value=details['email'], inline=True)
	embed.add_field(name='Posted', value=f'<t:{timestamp}:R>', inline=True)
	embed.add_field(name='Subject', value=details['subject'], inline=False)
	embed.add_field(name='Link', value=f'[Click here to open](https://www.fit.ba/student/{details["href"]})', inline=False)
	embed.set_footer(text='01101111 01101101 01111010 01101110 01100011')

	response = requests.post(
		getenv('WEBHOOK_URL'),
		json={
			"content": f"<@&796116996000579644> {details['author']} posted a new thread{' in ' + details['subject'] if details['subject'] != '' else ''}!",
			"thread_name": f'{details["title"]}' if details["subject"] == '' else f'[{details["subject"]}] {details["title"]}',
			"embeds": [embed.to_dict()],
			"username": details['author'],
			"avatar_url": AVATARS.get(details['author'].split(' ')[0], "https://ui-avatars.com/api/?name=" + details['author'].replace(' ', '+'))
		},
		headers={
			"Content-Type": "application/json"
		}
	)

	if response.status_code == 204:
		print("Discord webhook sent successfully.")
	else:
		print("Failed to send Discord webhook.")


if __name__ == "__main__":

	required_variables = ['WEBHOOK_URL', 'USERNAME', 'PASSWORD']
	missing_variables = [var for var in required_variables if getenv(var) is None]
	if missing_variables:
		for var in missing_variables:
			print(f'{var} environment variable not set.')
		exit(1)
	import os

	if not os.path.exists(FILE_NAME):
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

				time.sleep(int(INTERVAL))
				runs += 1
		print("Logged in!")


