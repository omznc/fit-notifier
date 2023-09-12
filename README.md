## Usage

To use the application, follow these steps:

1. Clone the repository.
2. Install Docker on your machine.
3. Create a `.env` file in the root directory of the project and set the following environment variables:
   - `WEBHOOK_URL`: The Discord webhook URL to send notifications to.
   - `USERNAME`: Your FIT BA student username.
   - `PASSWORD`: Your FIT BA student password.
   - `INTERVAL`: The interval (in seconds) between each scrape.
4. Start the application by running the following command:
   ```
   docker compose up # You can use --build to force update the image after git pull
   ```