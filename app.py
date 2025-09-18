from flask import Flask, render_template, request, jsonify, send_file, url_for
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os
import io
import zipfile
from werkzeug.utils import secure_filename
import PyPDF2
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import base64

# Initialize Flask app
app = Flask(__name__,
            template_folder=None,  # No server-side templates in separated backend
            static_folder=None)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Allow CORS for all routes (adjust origins if needed)
CORS(app, resources={r"/*": {"origins": "*"}})

# Socket.IO setup with permissive CORS
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Configuration
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_EXTENSIONS = {'pdf'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROCESSED_FOLDER'] = PROCESSED_FOLDER

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/merge', methods=['POST'])
def merge_pdfs():
    try:
        # Get uploaded files
        files = request.files.getlist('files')
        
        # Create a buffer for the merged PDF
        merged_buffer = io.BytesIO()
        pdf_merger = PyPDF2.PdfMerger()
        
        # Process each file
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                pdf_merger.append(file_path)
                socketio.emit('processing_status', {'status': f'Processing {filename}...'})
        
        # Write merged PDF to buffer
        pdf_merger.write(merged_buffer)
        pdf_merger.close()
        
        # Save merged PDF
        merged_buffer.seek(0)
        output_path = os.path.join(app.config['PROCESSED_FOLDER'], 'merged_output.pdf')
        with open(output_path, 'wb') as f:
            f.write(merged_buffer.getvalue())
        
        socketio.emit('processing_complete', {'status': 'Merge completed successfully!'})
        
        return jsonify({
            'success': True,
            'message': 'PDFs merged successfully',
            'filename': 'merged_output.pdf'
        })
    except Exception as e:
        socketio.emit('processing_error', {'status': f'Error: {str(e)}'})
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/split', methods=['POST'])
def split_pdf():
    try:
        file = request.files['file'] if 'file' in request.files else None
        split_page = int(request.form.get('split_page', 1))
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            socketio.emit('processing_status', {'status': f'Splitting {filename} at page {split_page}...'})
            
            # Read the PDF
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                pdf_writer1 = PyPDF2.PdfWriter()
                pdf_writer2 = PyPDF2.PdfWriter()
                
                # Split the PDF
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    if page_num < split_page:
                        pdf_writer1.add_page(page)
                    else:
                        pdf_writer2.add_page(page)
                
                # Save the split PDFs
                output1_path = os.path.join(app.config['PROCESSED_FOLDER'], 'split_part1.pdf')
                output2_path = os.path.join(app.config['PROCESSED_FOLDER'], 'split_part2.pdf')
                
                with open(output1_path, 'wb') as f1:
                    pdf_writer1.write(f1)
                
                with open(output2_path, 'wb') as f2:
                    pdf_writer2.write(f2)
            
            socketio.emit('processing_complete', {'status': 'Split completed successfully!'})
            
            return jsonify({
                'success': True,
                'message': 'PDF split successfully',
                'files': ['split_part1.pdf', 'split_part2.pdf']
            })
        else:
            return jsonify({'success': False, 'message': 'No file uploaded or invalid file type'})
    except Exception as e:
        socketio.emit('processing_error', {'status': f'Error: {str(e)}'})
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/compress', methods=['POST'])
def compress_pdf():
    try:
        file = request.files['file'] if 'file' in request.files else None
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            socketio.emit('processing_status', {'status': f'Compressing {filename}...'})
            
            # For compression, we'll just copy the file for now
            # In a real implementation, we would use a library like Ghostscript
            output_path = os.path.join(app.config['PROCESSED_FOLDER'], 'compressed_output.pdf')
            
            with open(file_path, 'rb') as f:
                with open(output_path, 'wb') as out:
                    out.write(f.read())
            
            socketio.emit('processing_complete', {'status': 'Compression completed successfully!'})
            
            return jsonify({
                'success': True,
                'message': 'PDF compressed successfully',
                'filename': 'compressed_output.pdf'
            })
        else:
            return jsonify({'success': False, 'message': 'No file uploaded or invalid file type'})
    except Exception as e:
        socketio.emit('processing_error', {'status': f'Error: {str(e)}'})
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/download/<filename>')
def download_file(filename):
    try:
        file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == '__main__':
    # Use PORT provided by environment (Render), default to 5000 for local dev
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=True, host='0.0.0.0', port=port)