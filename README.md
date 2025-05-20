> This was done in ~20 minutes. Do not expect nice code.

## Usage

To use the application, follow these steps:

1. Clone the repository.
2. Install Docker on your machine.
3. Create a `.env` file in the root directory of the project and set the following environment variables:
   - `WEBHOOK_URL`: The Discord webhook URL to send notifications to.
   - `USERNAME`: Your student username.
   - `PASSWORD`: Your student password.
   - `INTERVAL`: The interval (in seconds) between each scrape. Defaults to 10s.
4. Start the application by running the following command:
   ```
   docker compose up # You can use --build to force update the image after git pull
   ```

![image](https://github.com/user-attachments/assets/087abeb8-d93d-4a61-aa4d-52c808b965b5)
