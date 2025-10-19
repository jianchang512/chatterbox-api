host = '127.0.0.1'
port = 5093
threads = 4

import os,time,shutil,sys
#os.environ['htts_proxy']='http://127.0.0.1:10808'
#os.environ['htt_proxy']='http://127.0.0.1:10808'
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
#from chatterbox.tts import ChatterboxTTS
ROOT_DIR=Path(os.getcwd()).as_posix()
# 对于国内用户，使用Hugging Face镜像能显著提高下载速度
os.environ['HF_HOME'] = ROOT_DIR + "/models"
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = 'true'
os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = 'true'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = "1200"

import subprocess,traceback
import io
import uuid
import tempfile
from flask import Flask, request, jsonify, send_file, render_template, make_response
from waitress import serve
import torch
import torchaudio as ta

try:
    import soundfile as sf
except ImportError:
    print('No soundfile, exec cmd ` runtime\python -m pip install soundfile`')
    sys.exit()

try:    
    from pydub import AudioSegment
except ImportError:
    print('No soundfile, exec cmd ` runtime\python -m pip install pydub`')
    sys.exit()


if sys.platform == 'win32':
    os.environ['PATH'] = ROOT_DIR + f';{ROOT_DIR}/ffmpeg;{ROOT_DIR}/tools;' + os.environ['PATH']
from chatterbox.mtl_tts import ChatterboxMultilingualTTS as ChatterboxTTS

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
    #if lang != 'en':
    #    return jsonify({"error": "Only support English"}), 400


    if not text:
        return jsonify({"error": "Missing 'input' field in request body"}), 400
    
    print(f"[APIv1] Received text: '{text[:50]}...'")

    try:
        # 生成WAV音频
        wav_tensor = model.generate(text,exaggeration=exaggeration,cfg_weight=cfg_weight,language_id=lang)

        # 检查请求的响应格式，默认为mp3
        response_format = data.get('response_format', 'mp3').lower()
        download_name=f'{time.time()}'

        # 对于其他格式（如wav），直接返回
        wav_buffer = io.BytesIO()
        wav_tensor = wav_tensor.detach().cpu()
        if wav_tensor.ndim == 2:
            wav_np = wav_tensor.transpose(0, 1).numpy()
        else:
            wav_np = wav_tensor.numpy()
         # 写入 WAV 格式到内存
        sf.write(wav_buffer, wav_np, model.sr, format='wav')
        wav_buffer.seek(0)
        if response_format=='mp3':
            mp3_buffer = io.BytesIO()
            AudioSegment.from_file(wav_buffer, format="wav").export(mp3_buffer, format="mp3")
            mp3_buffer.seek(0)

            return send_file(
                mp3_buffer,
                mimetype='audio/mpeg',
                as_attachment=False,
                download_name=f'{download_name}.mp3'
            )
        
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
    #if lang != 'en':
    #    return jsonify({"error": "Only support English"}), 400
    
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
        wav_tensor = model.generate(text, audio_prompt_path=temp_wav_path,exaggeration=exaggeration,cfg_weight=cfg_weight,language_id=lang)
        
        # --- Stage 4: Format and Return Response Based on Request ---
        download_name=f'{time.time()}'

        print("   - Formatting response as WAV.")
        wav_buffer = io.BytesIO()
        wav_tensor = wav_tensor.detach().cpu()
        if wav_tensor.ndim == 2:
            wav_np = wav_tensor.transpose(0, 1).numpy()
        else:
            wav_np = wav_tensor.numpy()
         # 写入 WAV 格式到内存
        sf.write(wav_buffer, wav_np, model.sr, format='wav')
        wav_buffer.seek(0)
        if response_format == 'mp3':
            mp3_buffer = io.BytesIO()
            AudioSegment.from_file(wav_buffer, format="wav").export(mp3_buffer, format="mp3")
            mp3_buffer.seek(0)
            return send_file(
                mp3_buffer,
                mimetype='audio/mpeg',
                as_attachment=False,
                download_name=f'{download_name}.mp3'
            )

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