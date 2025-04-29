import os
import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, generate_blob_sas, BlobSasPermissions

load_dotenv()
app = Flask(__name__)

# Azure SQL Database connection details
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.urandom(24)

# Initialize database
db = SQLAlchemy(app)

# Azure Blob Storage connection details
BLOB_STORAGE_CONNECTION_STRING = os.getenv('BLOB_STORAGE_CONNECTION_STRING')
CONTAINER_NAME = os.getenv('CONTAINER_NAME')

# Extract account name and account key from the connection string
def extract_account_info(connection_string):
    account_name = None
    account_key = None
    for part in connection_string.split(';'):
        if part.startswith('AccountName'):
            account_name = part.split('=')[1]
        elif part.startswith('AccountKey'):
            account_key = part.split('=')[1]
    if not account_name or not account_key:
        raise ValueError("Account name or account key not found in the connection string.")
    return account_name, account_key

account_name, account_key = extract_account_info(BLOB_STORAGE_CONNECTION_STRING)
blob_service_client = BlobServiceClient.from_connection_string(BLOB_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Ensure the container exists
try:
    container_client.get_container_properties()
except Exception:
    container_client.create_container()
    print(f"Container '{CONTAINER_NAME}' created successfully.")

# Define the Note model
class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(255), nullable=False)

# Create the table only if it doesn't exist
with app.app_context():
    inspector = db.inspect(db.engine)
    if 'note' not in inspector.get_table_names():
        db.create_all()

# Routes
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        new_note = request.form['note']
        if new_note.strip():
            note = Note(content=new_note)
            db.session.add(note)
            db.session.commit()
        return redirect(url_for('index'))

    notes = Note.query.all()

    uploaded_images = []
    blobs = container_client.list_blobs()
    for blob in blobs:
        image_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{blob.name}"
        uploaded_images.append(image_url)

    return render_template('index.html', notes=notes, uploaded_images=uploaded_images)

@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    note_to_delete = Note.query.get_or_404(id)
    db.session.delete(note_to_delete)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return "No file part"
    
    file = request.files['file']
    if file.filename == '':
        return "No selected file"
    
    try:
        blob_client = container_client.get_blob_client(file.filename)
        blob_client.upload_blob(file, overwrite=True)

        blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{file.filename}"
        return f"File uploaded successfully! Access it at: <a href='{blob_url}' target='_blank'>{blob_url}</a>"
    except Exception as e:
        return f"Error uploading file: {str(e)}"

@app.route('/delete_image/<string:image_name>', methods=['POST'])
def delete_image(image_name):
    try:
        blob_client = container_client.get_blob_client(image_name)
        blob_client.delete_blob()
        return redirect(url_for('index'))
    except Exception as e:
        return f"Error deleting image: {str(e)}"

# Generate a SAS token for secure blob access
def generate_sas_token(blob_name):
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    )
    if len(sas_token) % 4 != 0:
        sas_token = sas_token + "=" * (4 - len(sas_token) % 4)
    return sas_token

# Construct a full URL for blob download using SAS token
def get_blob_url(blob_name, sas_token):
    return f"https://{account_name}.blob.core.windows.net/{CONTAINER_NAME}/{blob_name}?{sas_token}"

@app.route('/download_image/<string:image_name>', methods=['GET'])
def download_image(image_name):
    try:
        sas_token = generate_sas_token(image_name)
        download_url = get_blob_url(image_name, sas_token)
        return redirect(download_url)
    except Exception as e:
        return f"Error downloading image: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
