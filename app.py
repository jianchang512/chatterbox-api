host = '127.0.0.1'
port = 5093
threads = 4


import os,time,shutil
import sys
import subprocess
import io
import uuid
import tempfile
from flask import Flask, request, jsonify, send_file, render_template, make_response
from waitress import serve
import torch
import torchaudio as ta
from pathlib import Path

from chatterbox.tts import ChatterboxTTS
ROOT_DIR=Path(os.getcwd()).as_posix()

# 对于国内用户，使用Hugging Face镜像能显著提高下载速度
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
if sys.platform == 'win32':
    os.environ['PATH'] = ROOT_DIR + f';{ROOT_DIR}/ffmpeg;{ROOT_DIR}/tools;' + os.environ['PATH']
# 检查ffmpeg是否安装
def check_ffmpeg():
    """检查系统中是否安装了ffmpeg"""
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
        print("FFmpeg 已安装.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: 不存在ffmpeg，请先安装ffmpeg.")
        sys.exit(1) # 强制退出，因为MP3转换是必须功能

# 加载Chatterbox TTS模型
def load_tts_model():
    """加载TTS模型到指定设备"""
    print("⏳ 开始加载模型 ChatterboxTTS model... 请耐心等待.")
    try:
        # 自动检测可用设备 (CUDA > CPU)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {device}")
        
        # 从预训练模型加载
        tts_model = ChatterboxTTS.from_pretrained(device=device)
        print("模型加载完成.")
        return tts_model
    except Exception as e:
        print(f"FATAL: 模型加载失败: {e}")
        sys.exit(1)

# --- 全局变量初始化 ---
check_ffmpeg()
model = load_tts_model()
app = Flask(__name__)


# --- 工具函数 ---
def convert_wav_to_mp3(wav_tensor, sample_rate):
    """
    使用ffmpeg将WAV张量转换为MP3字节流 (使用 subprocess.run)。
    """
    # 1. 将PyTorch张量保存到内存中的WAV文件
    wav_buffer = io.BytesIO()
    ta.save(wav_buffer, wav_tensor, sample_rate, format="wav")
    wav_buffer.seek(0)
    wav_data_bytes = wav_buffer.read() # 读取为字节数据

    # 2. 定义 ffmpeg 命令
    command = [
        'ffmpeg', 
        '-i', 'pipe:0',      # 从标准输入读取
        '-f', 'mp3',         # 指定输出格式为MP3
        '-q:a', '2',         # 设置MP3音质 (0-9, 0最高)，2是很好的平衡
        'pipe:1'             # 将输出写入标准输出
    ]

    try:
        # 3. 使用 subprocess.run 执行转换
        #    - input: 将WAV字节数据传递给ffmpeg的stdin
        #    - capture_output: 捕获stdout和stderr
        #    - check: 如果ffmpeg返回错误码，则自动抛出异常
        result = subprocess.run(
            command,
            input=wav_data_bytes,
            capture_output=True,
            check=True
        )
        
        # 如果成功，result.stdout 包含二进制的MP3数据
        return io.BytesIO(result.stdout)

    except subprocess.CalledProcessError as e:
        # 如果ffmpeg执行失败 (check=True 抛出异常)
        # 从字节解码stderr以显示可读的错误信息
        stderr_output = e.stderr.decode('utf-8', errors='ignore')
        error_message = f"ffmpeg MP3 conversion failed:\n{stderr_output}"
        print(f"{error_message}")
        raise RuntimeError(error_message) # 将其作为服务器内部错误重新抛出
    
    except FileNotFoundError:
        # 如果 ffmpeg 命令本身都找不到
        error_message = "ffmpeg not found. Please ensure ffmpeg is installed and in the system's PATH."
        print(f"{error_message}")
        raise RuntimeError(error_message)


def convert_to_wav(input_path, output_path, sample_rate=16000):
    """
    Converts any audio file to a standardized WAV format using ffmpeg.
    - 16-bit PCM
    - Specified sample rate (default 16kHz, common for TTS)
    - Mono channel
    """
    print(f"   - Converting '{input_path}' to WAV at {sample_rate}Hz...")
    command = [
        'ffmpeg',
        '-i', input_path,      # Input file
        '-y',                  # Overwrite output file if it exists
        '-acodec', 'pcm_s16le',# Use 16-bit PCM encoding
        '-ar', str(sample_rate),# Set audio sample rate
        '-ac', '1',            # Set to 1 audio channel (mono)
        output_path            # Output file
    ]
    try:
        process = subprocess.run(
            command, 
            check=True,          # Raise an exception if ffmpeg fails
            capture_output=True, # Capture stdout and stderr
            text=True,            # Decode stdout/stderr as text
            encoding='utf-8',     # 明确指定使用 UTF-8 解码
            errors='replace'      # 如果遇到解码错误，用'�'替换，而不是崩溃

        )
        print(f"   - FFmpeg conversion successful.")
    except subprocess.CalledProcessError as e:
        # If ffmpeg fails, print its error output for easier debugging
        print("FFmpeg conversion failed!")
        print(f"   - Command: {' '.join(command)}")
        print(f"   - Stderr: {e.stderr}")
        raise e # Re-raise the exception to be caught by the main try...except block

# --- API 接口 ---

@app.route('/')
def index():
    """提供前端界面"""
    return render_template('index.html')

# 接口1: 兼容OpenAI TTS接口
@app.route('/v1/audio/speech', methods=['POST'])
def tts_openai_compatible():
    """
    OpenAI TTS兼容接口。
    接收JSON: {"input": "text", "model": "chatterbox", "voice": "default", ...}
    `model`和`voice`参数会被接收但当前实现中忽略。
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    text = data.get('input')
    # voice 用来接收语言代码
    lang=data.get('voice','en')
    # speed用于接收 cfg_weight
    cfg_weight=float(data.get('speed',0.5))
    # instructions 用于接收 exaggeration
    exaggeration=float(data.get('instructions',0.5))
    if lang != 'en':
        return jsonify({"error": "Only support English"}), 400


    if not text:
        return jsonify({"error": "Missing 'input' field in request body"}), 400
    
    print(f"[APIv1] Received text: '{text[:50]}...'")

    try:
        # 生成WAV音频
        wav_tensor = model.generate(text,exaggeration=exaggeration,cfg_weight=cfg_weight)

        # 检查请求的响应格式，默认为mp3
        response_format = data.get('response_format', 'mp3').lower()
        download_name=f'{time.time()}'
        if response_format == 'mp3':
            # 转换为MP3并返回
            mp3_buffer = convert_wav_to_mp3(wav_tensor, model.sr)
            return send_file(
                mp3_buffer,
                mimetype='audio/mpeg',
                as_attachment=False,
                download_name=f'{download_name}.mp3'
            )
        else:
            # 对于其他格式（如wav），直接返回
            wav_buffer = io.BytesIO()
            ta.save(wav_buffer, wav_tensor, model.sr, format="wav")
            wav_buffer.seek(0)
            return send_file(
                wav_buffer,
                mimetype='audio/wav',
                as_attachment=False,
                download_name=f'{download_name}.wav'
            )
            
    except Exception as e:
        print(f"[APIv1] Error during TTS generation: {e}")
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500


# 接口2: 带参考音频的TTS
@app.route('/v2/audio/speech_with_prompt', methods=['POST'])
def tts_with_prompt():
    """
    带参考音频的接口。
    接收 multipart/form-data:
    - 'input': (string) 要转换的文本
    - 'audio_prompt': (file) 参考音频文件
    """
    if 'input' not in request.form:
        return jsonify({"error": "Missing 'input' field in form data"}), 400
    if 'audio_prompt' not in request.files:
        return jsonify({"error": "Missing 'audio_prompt' file in form data"}), 400

    text = request.form['input']
    audio_file = request.files['audio_prompt']
    response_format = request.form.get('response_format', 'wav').lower()

    cfg_weight=float(request.form.get('cfg_weight',0.5))

    exaggeration=float(request.form.get('exaggeration',0.5))
    lang = request.form.get('language','en')
    if lang != 'en':
        return jsonify({"error": "Only support English"}), 400
    
    print(f"[APIv2] Received text: '{text[:50]}...' with audio prompt '{audio_file.filename}'")

    
    temp_upload_path = None
    temp_wav_path = None
    try:
        # --- Stage 1 & 2: Save and Convert uploaded file ---
        temp_dir = tempfile.gettempdir()
        upload_suffix = os.path.splitext(audio_file.filename)[1]
        temp_upload_path = os.path.join(temp_dir, f"{uuid.uuid4()}{upload_suffix}")
        audio_file.save(temp_upload_path)
        print(f"   - Uploaded audio saved to: {temp_upload_path}")

        temp_wav_path = os.path.join(temp_dir, f"{uuid.uuid4()}.wav")
        convert_to_wav(temp_upload_path, temp_wav_path)

        # --- Stage 3: Generate TTS using the converted WAV file ---
        print(f"   - Generating TTS with prompt: {temp_wav_path}")
        wav_tensor = model.generate(text, audio_prompt_path=temp_wav_path,exaggeration=exaggeration,cfg_weight=cfg_weight)
        
        # --- Stage 4: Format and Return Response Based on Request ---
        download_name=f'{time.time()}'
        if response_format == 'mp3':
            print("   - Formatting response as MP3.")
            mp3_buffer = convert_wav_to_mp3(wav_tensor, model.sr)
            return send_file(
                mp3_buffer,
                mimetype='audio/mpeg',
                as_attachment=False,
                download_name=f'{download_name}.mp3'
            )
        else: # Default to WAV
            print("   - Formatting response as WAV.")
            wav_buffer = io.BytesIO()
            # Note: We need torchaudio 'ta' imported, which should be at the top of the file
            ta.save(wav_buffer, wav_tensor, model.sr, format="wav")
            wav_buffer.seek(0) # IMPORTANT: Rewind buffer to the beginning before sending
            return send_file(
                wav_buffer,
                mimetype='audio/wav',
                as_attachment=False,
                download_name=f'{download_name}.wav'
            )

    except Exception as e:
        print(f"[APIv2] An error occurred: {e}")
        traceback.print_exc()
        return jsonify({"error": f"An internal error occurred: {str(e)}"}), 500
    
    finally:
        # --- Stage 5: Cleanup ---
        if temp_upload_path and os.path.exists(temp_upload_path):
            try:
                os.remove(temp_upload_path)
                print(f"   - Cleaned up upload file: {temp_upload_path}")
            except OSError as e:
                print(f"   - Error cleaning up upload file {temp_upload_path}: {e}")
        
        if temp_wav_path and os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
                print(f"   - Cleaned up WAV file: {temp_wav_path}")
            except OSError as e:
                print(f"   - Error cleaning up WAV file {temp_wav_path}: {e}")


# --- 服务启动 ---
if __name__ == '__main__':

    print(f"\n服务启动完成，http地址是： http://{host}:{port}  \n")
    serve(app, host=host, port=port, threads=threads)