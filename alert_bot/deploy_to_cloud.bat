@echo off
echo --- Starting GCP Deployment for AlertScanner ---
echo Setting project to nextoffice-main...
gcloud config set project nextoffice-main

echo.
echo Deploying Cloud Run Job 'alert-scanner-job'...
gcloud run jobs deploy alert-scanner-job --source . --region me-west1 --max-retries 0

echo.
echo Creating Cloud Scheduler Job (Every 15 min during US market hours)...
gcloud scheduler jobs create http alert-scanner-scheduler ^
  --location=me-west1 ^
  --schedule="*/15 16-23 * * 1-5" ^
  --time-zone="Asia/Jerusalem" ^
  --uri="https://me-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nextoffice-main/jobs/alert-scanner-job:run" ^
  --http-method=POST ^
  --oauth-service-account-email="yosef@agentnextoffice.com"

echo.
echo Deployment Complete!
pause
