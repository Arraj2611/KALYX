#!/bin/bash

echo "Setting up KALYX Trading System..."

# Backend setup
echo "Setting up backend..."
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend setup
echo "Setting up frontend..."
cd frontend
npm install
cd ..

# Docker setup
echo "Setting up Docker services..."
cd docker
docker-compose up -d
cd ..

echo "Setup complete!"
echo "Don't forget to:"
echo "1. Copy .env.example to .env and configure your credentials"
echo "2. Start the backend: cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
echo "3. Start the frontend: cd frontend && npm run dev"

