# Librus Synchronizer

Librus Synchronizer is a tool designed to synchronize data from the Librus school management system, enabling users to efficiently manage and access their educational information.

## Features

- **Data Synchronization**: Automatically fetch and update events data from the Librus platform.
- **Secure**: Ensures the safety and privacy of your data.

## Setup

I would recommend to just fork the repository and setup GitHub Actions secrets as follows:

1. Create a service account in Google Cloud Console.
1. Download the JSON key file.
1. Share your calendar with the service account’s email address (found in the JSON file).
1. Store the JSON key as a GitHub Actions secret (e.g., `G_SERVICE_ACCOUNT_JSON`).`
1. Store the Librus account credentials in. `LIBRUS_USERNAME` and `LIBRUS_PASSWORD` as GitHub Actions secrets
1. Store google's calendar ID, as `CALENDAR_ID` secret
1. Customize `run_synchronization.yml` per your needs