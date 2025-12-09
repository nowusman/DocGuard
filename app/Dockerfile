FROM python:3.12-slim
# set work dir
WORKDIR /app
# copy currently files to work dir
COPY . .
# limit thread oversubscription across spaCy/OCR
ENV OMP_NUM_THREADS=1
# install required package
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm
# minimal native deps for imaging/OCR backends
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 ghostscript && rm -rf /var/lib/apt/lists/*
# # expose port 8000
# EXPOSE 8000
# # run api
# CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
# expose port 8501
EXPOSE 8501
# run app.py
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
