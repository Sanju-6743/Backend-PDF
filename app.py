import os
import io
import zipfile
import tempfile
import shutil
from flask import Flask, request, jsonify, send_file
from flask_socketio import SocketIO
from flask_cors import CORS
from werkzeug.utils import secure_filename
import PyPDF2
from PIL import Image
from pdf2image import convert_from_path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key'
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Allowed extensions
ALLOWED_PDF = {'pdf'}
ALLOWED_IMG = {'png', 'jpg', 'jpeg'}

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def create_temp_dir():
    """Creates a temporary directory and returns its path."""
    return tempfile.mkdtemp()

def cleanup_dir(dir_path):
    """Removes a directory and its contents."""
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)

def emit_progress(sid, percent, message):
    """Emits a progress update to a specific client."""
    socketio.emit('processing_progress', {'percent': percent, 'message': message}, room=sid)

@app.route('/merge', methods=['POST'])
def merge_pdfs():
    sid = request.headers.get('X-SocketIO-SID')
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files uploaded'}), 400
    
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'success': False, 'message': 'No files selected'}), 400

    temp_dir = create_temp_dir()
    try:
        pdf_merger = PyPDF2.PdfMerger()
        total_files = len(files)
        
        for i, file in enumerate(files):
            if file and allowed_file(file.filename, ALLOWED_PDF):
                filename = secure_filename(file.filename)
                file_path = os.path.join(temp_dir, filename)
                file.save(file_path)
                pdf_merger.append(file_path)
                emit_progress(sid, int((i + 1) / total_files * 100), f'Merging {filename}...')
            else:
                raise ValueError("Invalid file type found.")

        output_filename = 'merged_output.pdf'
        output_path = os.path.join(temp_dir, output_filename)
        pdf_merger.write(output_path)
        pdf_merger.close()

        return send_file(output_path, as_attachment=True, download_name=output_filename)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@app.route('/split', methods=['POST'])
def split_pdf():
    sid = request.headers.get('X-SocketIO-SID')
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    
    file = request.files['file']
    split_ranges = request.form.get('ranges') # e.g., "1-3, 5, 7-9"
    if not file or not split_ranges:
        return jsonify({'success': False, 'message': 'Missing file or split ranges'}), 400

    temp_dir = create_temp_dir()
    try:
        file_path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(file_path)
        
        pdf_reader = PyPDF2.PdfReader(file_path)
        total_pages = len(pdf_reader.pages)
        
        # Parse ranges
        pages_to_extract = set()
        for part in split_ranges.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                pages_to_extract.update(range(start - 1, end))
            else:
                pages_to_extract.add(int(part) - 1)
        
        pdf_writer = PyPDF2.PdfWriter()
        for i, page_num in enumerate(sorted(list(pages_to_extract))):
            if 0 <= page_num < total_pages:
                pdf_writer.add_page(pdf_reader.pages[page_num])
            emit_progress(sid, int((i + 1) / len(pages_to_extract) * 100), f'Extracting page {page_num + 1}...')

        output_filename = 'split_output.pdf'
        output_path = os.path.join(temp_dir, output_filename)
        with open(output_path, 'wb') as f:
            pdf_writer.write(f)
            
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@app.route('/pdf-to-jpg', methods=['POST'])
def pdf_to_jpg():
    sid = request.headers.get('X-SocketIO-SID')
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400
    
    file = request.files['file']
    temp_dir = create_temp_dir()
    try:
        file_path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(file_path)
        
        emit_progress(sid, 10, 'Converting PDF to images...')
        images = convert_from_path(file_path)
        
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, image in enumerate(images):
                img_filename = f'page_{i + 1}.jpg'
                img_path = os.path.join(temp_dir, img_filename)
                image.save(img_path, 'JPEG')
                zf.write(img_path, img_filename)
                emit_progress(sid, 10 + int((i + 1) / len(images) * 90), f'Zipping page {i + 1}...')

        zip_buffer.seek(0)
        return send_file(zip_buffer, as_attachment=True, download_name='pdf_to_jpg.zip', mimetype='application/zip')
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@app.route('/images-to-pdf', methods=['POST'])
def images_to_pdf():
    sid = request.headers.get('X-SocketIO-SID')
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No images uploaded'}), 400
        
    files = request.files.getlist('files')
    temp_dir = create_temp_dir()
    try:
        image_paths = []
        for file in files:
            if file and allowed_file(file.filename, ALLOWED_IMG):
                file_path = os.path.join(temp_dir, secure_filename(file.filename))
                file.save(file_path)
                image_paths.append(file_path)
        
        if not image_paths:
            raise ValueError("No valid images found.")
            
        pil_images = []
        for i, path in enumerate(image_paths):
            pil_images.append(Image.open(path).convert('RGB'))
            emit_progress(sid, int((i + 1) / len(image_paths) * 50), f'Processing image {i + 1}...')

        output_filename = 'images_to_pdf.pdf'
        output_path = os.path.join(temp_dir, output_filename)
        
        pil_images[0].save(output_path, save_all=True, append_images=pil_images[1:])
        emit_progress(sid, 100, 'PDF created.')

        return send_file(output_path, as_attachment=True, download_name=output_filename)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@app.route('/protect', methods=['POST'])
def protect_pdf():
    sid = request.headers.get('X-SocketIO-SID')
    if 'file' not in request.files or 'password' not in request.form:
        return jsonify({'success': False, 'message': 'Missing file or password'}), 400
        
    file = request.files['file']
    password = request.form['password']
    temp_dir = create_temp_dir()
    try:
        file_path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(file_path)
        
        pdf_reader = PyPDF2.PdfReader(file_path)
        pdf_writer = PyPDF2.PdfWriter()
        
        for i, page in enumerate(pdf_reader.pages):
            pdf_writer.add_page(page)
            emit_progress(sid, int((i + 1) / len(pdf_reader.pages) * 100), f'Processing page {i + 1}...')
            
        pdf_writer.encrypt(password)
        
        output_filename = 'protected.pdf'
        output_path = os.path.join(temp_dir, output_filename)
        with open(output_path, 'wb') as f:
            pdf_writer.write(f)
            
        return send_file(output_path, as_attachment=True, download_name=output_filename)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@app.route('/add-watermark', methods=['POST'])
def add_watermark():
    sid = request.headers.get('X-SocketIO-SID')
    if 'file' not in request.files or 'watermark_text' not in request.form:
        return jsonify({'success': False, 'message': 'Missing file or watermark text'}), 400

    file = request.files['file']
    watermark_text = request.form['watermark_text']
    temp_dir = create_temp_dir()
    try:
        file_path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(file_path)

        # Create watermark PDF
        watermark_io = io.BytesIO()
        c = canvas.Canvas(watermark_io, pagesize=letter)
        c.setFont("Helvetica", 50)
        c.setFillAlpha(0.1)
        c.rotate(45)
        c.drawString(300, 0, watermark_text)
        c.save()
        watermark_io.seek(0)
        watermark_pdf = PyPDF2.PdfReader(watermark_io)
        watermark_page = watermark_pdf.pages[0]

        # Add watermark to each page
        pdf_reader = PyPDF2.PdfReader(file_path)
        pdf_writer = PyPDF2.PdfWriter()
        
        for i, page in enumerate(pdf_reader.pages):
            page.merge_page(watermark_page)
            pdf_writer.add_page(page)
            emit_progress(sid, int((i + 1) / len(pdf_reader.pages) * 100), f'Adding watermark to page {i + 1}...')

        output_filename = 'watermarked.pdf'
        output_path = os.path.join(temp_dir, output_filename)
        with open(output_path, 'wb') as f:
            pdf_writer.write(f)

        return send_file(output_path, as_attachment=True, download_name=output_filename)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cleanup_dir(temp_dir)

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=True, host='0.0.0.0', port=port)
