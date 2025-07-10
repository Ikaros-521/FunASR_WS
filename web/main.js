/**
 * Copyright FunASR (https://github.com/alibaba-damo-academy/FunASR). All Rights
 * Reserved. MIT License  (https://opensource.org/licenses/MIT)
 */
/* 2022-2023 by zhaoming,mali aihealthx.com */


// 连接; 定义socket连接类对象与语音对象
var wsconnecter = new WebSocketConnectMethod({ msgHandle: getJsonMessage, stateHandle: getConnState });
var audioBlob;

// 录音; 定义录音对象,wav格式
var rec = Recorder({
	type: "pcm",
	bitRate: 16,
	sampleRate: 16000,
	onProcess: recProcess
});


var sampleBuf = new Int16Array();
// 定义按钮响应事件
var btnStart = document.getElementById('btnStart');
btnStart.onclick = record;
var btnStop = document.getElementById('btnStop');
btnStop.onclick = stop;
btnStop.disabled = true;
btnStart.disabled = true;

btnConnect = document.getElementById('btnConnect');
btnConnect.onclick = start;

var awsslink = document.getElementById('wsslink');

var rec_text = "";  // for online rec asr result
var offline_text = ""; // for offline rec asr result
var info_div = document.getElementById('info_div');

var upfile = document.getElementById('upfile');

var isfilemode = false;  // if it is in file mode
var file_ext = "";
var file_sample_rate = 16000; //for wav file sample rate
var file_data_array;  // array to save file data

var totalsend = 0;

// 数据转发模式
var data_forward = "none";


// 构建url
function buildUrl(baseUrl, endpoint) {
    // 创建一个新的URL对象并设置其pathname为endpoint
    const url = new URL(baseUrl);
    url.pathname = new URL(endpoint, 'http://dummy.com').pathname;
  
    return url.toString();
}

// 自动设置wssip输入框为当前页面协议和IP
(function setWssipByLocation() {
    var protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    var host = window.location.hostname;
    var wssip = protocol + host + ':10096/';
    var wssipInput = document.getElementById('wssip');
    if (wssipInput) {
        wssipInput.value = wssip;
    }
})();

addresschange();
function addresschange() {

	var Uri = document.getElementById('wssip').value;
	// document.getElementById('info_wslink').innerHTML = "点此处手工授权（IOS手机）";
	Uri = Uri.replace(/wss/g, "https");
	console.log("addresschange uri=", Uri);

	awsslink.onclick = function () {
		window.open(Uri, '_blank');
	}

}

upfile.onclick = function () {
	btnStart.disabled = true;
	btnStop.disabled = true;
	btnConnect.disabled = false;

}

// from https://github.com/xiangyuecn/Recorder/tree/master
var readWavInfo = function (bytes) {
	//读取wav文件头，统一成44字节的头
	if (bytes.byteLength < 44) {
		return null;
	};
	var wavView = bytes;
	var eq = function (p, s) {
		for (var i = 0; i < s.length; i++) {
			if (wavView[p + i] != s.charCodeAt(i)) {
				return false;
			};
		};
		return true;
	};

	if (eq(0, "RIFF") && eq(8, "WAVEfmt ")) {

		var numCh = wavView[22];
		if (wavView[20] == 1 && (numCh == 1 || numCh == 2)) {//raw pcm 单或双声道
			var sampleRate = wavView[24] + (wavView[25] << 8) + (wavView[26] << 16) + (wavView[27] << 24);
			var bitRate = wavView[34] + (wavView[35] << 8);
			var heads = [wavView.subarray(0, 12)], headSize = 12;//head只保留必要的块
			//搜索data块的位置
			var dataPos = 0; // 44 或有更多块
			for (var i = 12, iL = wavView.length - 8; i < iL;) {
				if (wavView[i] == 100 && wavView[i + 1] == 97 && wavView[i + 2] == 116 && wavView[i + 3] == 97) {//eq(i,"data")
					heads.push(wavView.subarray(i, i + 8));
					headSize += 8;
					dataPos = i + 8; break;
				}
				var i0 = i;
				i += 4;
				i += 4 + wavView[i] + (wavView[i + 1] << 8) + (wavView[i + 2] << 16) + (wavView[i + 3] << 24);
				if (i0 == 12) {//fmt 
					heads.push(wavView.subarray(i0, i));
					headSize += i - i0;
				}
			}
			if (dataPos) {
				var wavHead = new Uint8Array(headSize);
				for (var i = 0, n = 0; i < heads.length; i++) {
					wavHead.set(heads[i], n); n += heads[i].length;
				}
				return {
					sampleRate: sampleRate
					, bitRate: bitRate
					, numChannels: numCh
					, wavHead44: wavHead
					, dataPos: dataPos
				};
			};
		};
	};
	return null;
};

upfile.onchange = function () {
	var len = this.files.length;
	if (len === 0) {
		info_div.innerHTML = '请选择文件';
		return;
	}
	
	// 清空之前的结果
	clear();
	
	// 只处理第一个文件
	var selectedFile = this.files[0];
	file_ext = selectedFile.name.split('.').pop().toLowerCase();
	
	console.log("Selected file:", selectedFile.name, "Type:", selectedFile.type, "Size:", selectedFile.size, "bytes");
	
	// 检查文件类型
	var supportedTypes = ['wav', 'mp3', 'pcm'];
	if (!supportedTypes.includes(file_ext)) {
		info_div.innerHTML = '不支持的文件类型，请选择 WAV、MP3 或 PCM 文件';
		return;
	}
	
	// 读取文件数据
	let fileAudio = new FileReader();
	fileAudio.readAsArrayBuffer(selectedFile);
	
	fileAudio.onload = function () {
		file_data_array = fileAudio.result;
		console.log("File loaded, size:", file_data_array.byteLength, "bytes");
		
		// 对于 WAV 文件，获取采样率
		if (file_ext === "wav") {
			try {
				var audioData = new Uint8Array(file_data_array);
				var info = readWavInfo(audioData);
				if (info && info.sampleRate) {
					file_sample_rate = info.sampleRate;
					console.log("WAV sample rate:", file_sample_rate);
				} else {
					console.warn("Could not determine WAV sample rate, using default:", file_sample_rate);
				}
			} catch (e) {
				console.error("Error reading WAV info:", e);
			}
		}
		
		btnConnect.disabled = false;
		info_div.innerHTML = '文件已加载，请点击连接进行识别';
	};
	
	fileAudio.onerror = function (e) {
		console.error('File read error:', e);
		info_div.innerHTML = '文件读取错误，请重试';
	};
}

function play_file() {
	var audioblob = new Blob([new Uint8Array(file_data_array)], { type: "audio/wav" });
	var audio_record = document.getElementById('audio_record');
	audio_record.src = (window.URL || webkitURL).createObjectURL(audioblob);
	audio_record.controls = true;
	//audio_record.play();  //not auto play
}
function start_file_send() {
	if (!file_data_array || file_data_array.byteLength === 0) {
		console.error("文件数据为空");
		info_div.innerHTML = "文件数据为空，请重新选择文件";
		btnConnect.disabled = false;
		return;
	}

	// 清空之前的结果
	clear();
	
	console.log("开始发送文件数据，长度:", file_data_array.byteLength, "字节");
	sampleBuf = new Uint8Array(file_data_array);
	totalsend = 0;

	// 对于较大的文件，使用较大的块大小以提高传输效率
	var chunk_size = 1920; // 增大块大小，提高传输效率
	var total_chunks = Math.ceil(sampleBuf.length / chunk_size);
	var sent_chunks = 0;

	// 定时发送数据，避免一次性发送过多数据导致服务器处理不过来
	var sendInterval = setInterval(function() {
		if (sampleBuf.length <= 0) {
			clearInterval(sendInterval);
			console.log("所有数据已发送，总计:", totalsend, "字节");
			
			// 添加延迟，确保所有数据都被服务器接收
			setTimeout(function() {
				stop();
			}, 500);
			return;
		}

		var sendSize = Math.min(chunk_size, sampleBuf.length);
		var sendBuf = sampleBuf.slice(0, sendSize);
		sampleBuf = sampleBuf.slice(sendSize);
		
		try {
			wsconnecter.wsSend(sendBuf);
			totalsend += sendSize;
			sent_chunks++;
			
			// 更新进度信息
			var progress = Math.round((sent_chunks / total_chunks) * 100);
			info_div.innerHTML = "发送数据中: " + progress + "% (" + sent_chunks + "/" + total_chunks + ")";
		} catch (e) {
			console.error("发送数据时出错:", e);
			clearInterval(sendInterval);
			info_div.innerHTML = "发送数据时出错，请重试";
			btnConnect.disabled = false;
		}
	}, 5); // 每5ms发送一个数据块，提高传输速度
}

// 修改数据转发模式
function on_data_forward_change() {
	var item = null;
	var obj = document.getElementsByName("data_forward");
	for (var i = 0; i < obj.length; i++) { //遍历Radio 
		if (obj[i].checked) {
			item = obj[i].value;
			break;
		}
	}

	data_forward = item;
}

function on_recoder_mode_change() {
	var item = null;
	var obj = document.getElementsByName("recoder_mode");
	for (var i = 0; i < obj.length; i++) { //遍历Radio 
		if (obj[i].checked) {
			item = obj[i].value;
			break;
		}
	}
	if (item == "mic") {
		document.getElementById("mic_mode_div").style.display = 'block';
		document.getElementById("rec_mode_div").style.display = 'none';

		btnStart.disabled = true;
		btnStop.disabled = true;
		btnConnect.disabled = false;
		isfilemode = false;
	} else {
		document.getElementById("mic_mode_div").style.display = 'none';
		document.getElementById("rec_mode_div").style.display = 'block';

		btnStart.disabled = true;
		btnStop.disabled = true;
		btnConnect.disabled = true;
		isfilemode = true;
		info_div.innerHTML = '请点击选择文件';
	}
}


function getHotwords() {
	var obj = document.getElementById("varHot");

	if (typeof (obj) == 'undefined' || obj == null || obj.value.length <= 0) {
		return null;
	}
	let val = obj.value.toString();

	console.log("hotwords=" + val);
	let items = val.split(/[(\r\n)\r\n]+/);  //split by \r\n
	var jsonresult = {};
	const regexNum = /^[0-9]*$/; // test number
	for (item of items) {

		let result = item.split(" ");
		if (result.length >= 2 && regexNum.test(result[result.length - 1])) {
			var wordstr = "";
			for (var i = 0; i < result.length - 1; i++)
				wordstr = wordstr + result[i] + " ";

			jsonresult[wordstr.trim()] = parseInt(result[result.length - 1]);
		}
	}
	console.log("jsonresult=" + JSON.stringify(jsonresult));
	return JSON.stringify(jsonresult);

}
function getAsrMode() {

	var item = null;
	var obj = document.getElementsByName("asr_mode");
	for (var i = 0; i < obj.length; i++) { //遍历Radio 
		if (obj[i].checked) {
			item = obj[i].value;
			break;
		}
	}
	if (isfilemode) {
		item = "offline";
	}
	console.log("asr mode" + item);

	return item;
}

function handleWithTimestamp(tmptext, tmptime) {
	console.log("tmptext: " + tmptext);
	console.log("tmptime: " + tmptime);
	if (tmptime == null || tmptime == "undefined" || tmptext.length <= 0) {
		return tmptext;
	}
	tmptext = tmptext.replace(/。|？|，|、|\?|\.|\ /g, ","); // in case there are a lot of "。"
	var words = tmptext.split(",");  // split to chinese sentence or english words
	var jsontime = JSON.parse(tmptime); //JSON.parse(tmptime.replace(/\]\]\[\[/g, "],[")); // in case there are a lot segments by VAD
	var char_index = 0; // index for timestamp
	var text_withtime = "";
	for (var i = 0; i < words.length; i++) {
		if (words[i] == "undefined" || words[i].length <= 0) {
			continue;
		}
		console.log("words===", words[i]);
		console.log("words: " + words[i] + ",time=" + jsontime[char_index][0] / 1000);
		if (/^[a-zA-Z]+$/.test(words[i])) {   // if it is english
			text_withtime = text_withtime + jsontime[char_index][0] / 1000 + ":" + words[i] + "\n";
			char_index = char_index + 1;  //for english, timestamp unit is about a word
		}
		else {
			// if it is chinese
			text_withtime = text_withtime + jsontime[char_index][0] / 1000 + ":" + words[i] + "\n";
			char_index = char_index + words[i].length; //for chinese, timestamp unit is about a char
		}
	}
	return text_withtime;
}

const sleep = (delay) => new Promise((resolve) => setTimeout(resolve, delay))
async function is_speaking() {
	try {
		if (data_forward == "livetalking") {
			const response = await fetch(buildUrl(document.getElementById("livetalking_api_url").value, '/is_speaking'), {
				body: JSON.stringify({
					sessionid: 0,
				}),
				headers: {
					'Content-Type': 'application/json'
				},
				method: 'POST'
			});
			const data = await response.json();
			console.log('is_speaking res:', data)
			return data.data
		} else if (data_forward == "ai_vtuber") {
			const response = await fetch(buildUrl(document.getElementById("ai_vtuber_api_url").value, '/get_sys_info'), {
				headers: {
					'Content-Type': 'application/json'
				},
				method: 'GET'
			});
			const data = await response.json();
			console.log('is_speaking res:', data)
	
			// 如果等待播放和等待合成的消息数量都为0，则认为没有在说话
			if (data["data"]["audio"]["wait_play_audio_num"] == 0 && data["data"]["audio"]["wait_synthesis_msg_num"] == 0 &&
				data["data"]["metahuman-stream"]["wait_play_audio_num"] == 0 && data["data"]["metahuman-stream"]["wait_synthesis_msg_num"] == 0
			) {
				return false;
			} else {
				return true;
			}
		}
		
		return false
	} catch (error) {
		console.error('is_speaking error:', error)
		return false
	}
}

async function waitSpeakingEnd() {
	if (data_forward == "none") {
		return
	} else if (data_forward == "livetalking" || data_forward == "ai_vtuber") {
	    rec.stop() //关闭录音
		for (let i = 0; i < 10; i++) {  //等待数字人开始讲话，最长等待10s
			bspeak = await is_speaking()
			if (bspeak) {
				break
			}
			await sleep(1000)
		}

		while (true) {  //等待数字人讲话结束
			bspeak = await is_speaking()
			if (!bspeak) {
				break
			}
			await sleep(1000)
		}
		await sleep(2000)
		rec.start()
	} 
}
// 语音识别结果; 对jsonMsg数据解析,将识别结果附加到编辑框中
function getJsonMessage(jsonMsg) {
	try {
		console.log("Received message:", jsonMsg.data);
		var jsonData = JSON.parse(jsonMsg.data);
		var rectxt = jsonData['text'] || "";
		var asrmodel = jsonData['mode'] || "";
		var is_final = jsonData['is_final'];
		var timestamp = jsonData['timestamp'];
		var is_sentence_end = jsonData['is_sentence_end'] || false;
		
		// 记录接收到的消息，便于调试
		console.log("Mode:", asrmodel, "Text:", rectxt, "Is Final:", is_final, "Is Sentence End:", is_sentence_end);
		
		// 文件模式下特殊处理
		if (isfilemode) {
			console.log("处理文件模式的识别结果");
			
			// 过滤特殊字符
			rectxt = rectxt.replace(/<[^>]*>/g, '');
			
			// 添加到结果中，即使是空文本也要更新UI
			if (rectxt && rectxt.trim().length > 0) {
				console.log("有识别结果，添加到文本框");
				offline_text = offline_text + rectxt.replace(/ +/g, "") + '\n';
			} else {
				console.log("识别结果为空");
			}
			
			// 无论有无文本都更新显示
			rec_text = offline_text;
			var varArea = document.getElementById('varArea');
			varArea.value = rec_text;
			
			// 如果是最终结果，处理连接关闭
			if (is_final) {
				console.log("文件模式最终结果，准备关闭连接");
				play_file();
				
				// 延迟关闭连接，确保所有数据都被处理
				setTimeout(function() {
					wsconnecter.wsStop();
					
					// 根据是否有识别结果显示不同的提示
					if (rec_text && rec_text.trim().length > 0) {
						info_div.innerHTML = "识别完成，请点击连接";
					} else {
						info_div.innerHTML = "未能识别出文本，请尝试其他文件";
					}
					
					btnStart.disabled = true;
					btnStop.disabled = true;
					btnConnect.disabled = false;
				}, 2000); // 增加延迟时间到2秒
			}
			return;
		}
		
		// 非文件模式的处理逻辑
		if (asrmodel == "2pass-offline" || asrmodel == "offline") {
			// 过滤特殊字符
			rectxt = rectxt.replace(/<[^>]*>/g, '');
			
			// 只有在有文本内容时才添加到结果中
			if (rectxt && rectxt.trim().length > 0) {
				offline_text = offline_text + rectxt.replace(/ +/g, "") + '\n';
				rec_text = offline_text;
				
				if (data_forward == "livetalking") {
					fetch(buildUrl(document.getElementById("livetalking_api_url").value, '/human'), {
						body: JSON.stringify({
							text: rectxt.replace(/ +/g, ""),
							type: 'chat',
						}),
						headers: {
							'Content-Type': 'application/json'
						},
						method: 'POST'
					});
				} else if (data_forward == "ai_vtuber") {
					fetch(buildUrl(document.getElementById("ai_vtuber_api_url").value, '/send'), {
						body: JSON.stringify({
							type: 'comment',
							data: {
								"type": 'comment',
								"username": '主人',
								"content": rectxt.replace(/ +/g, ""),
							}
						}),
						headers: {
							'Content-Type': 'application/json'
						},
						method: 'POST'
					});
				}

				waitSpeakingEnd();
			}
		}
		else if (asrmodel == "2pass-sentence") {
			// 处理句子级别的识别结果
			if (rectxt && rectxt.trim().length > 0) {
				// 打印调试信息
				console.log("2pass-sentence模式收到文本:", JSON.stringify(rectxt));
				console.log("是否包含标点符号:", 
					rectxt.includes("。") || rectxt.includes("？") || rectxt.includes("！") || 
					rectxt.includes(".") || rectxt.includes("?") || rectxt.includes("!"));
				
				// 如果是句子结束或最终结果
				if (is_sentence_end || is_final) {
					// 过滤特殊字符
					rectxt = rectxt.replace(/<[^>]*>/g, '');
					console.log("过滤特殊字符后:", JSON.stringify(rectxt));
					
					// 如果是最终结果，替换整个文本
					if (is_final) {
						rec_text = rectxt.replace(/ +/g, "");
						console.log("最终结果:", JSON.stringify(rec_text));
					} else {
						// 否则添加新句子，保留标点符号
						rec_text = rec_text + rectxt.replace(/ +/g, "");
						console.log("添加新句子后:", JSON.stringify(rec_text));
						
						// 如果句子不是以换行符结束的，添加换行符
						if (!rec_text.endsWith('\n')) {
							rec_text = rec_text + '\n';
						}
					}
					
					// 转发到其他服务
					if (data_forward == "livetalking") {
						fetch(buildUrl(document.getElementById("livetalking_api_url").value, '/human'), {
							body: JSON.stringify({
								text: rectxt.replace(/ +/g, ""),
								type: 'chat',
							}),
							headers: {
								'Content-Type': 'application/json'
							},
							method: 'POST'
						});
					} else if (data_forward == "ai_vtuber") {
						fetch(buildUrl(document.getElementById("ai_vtuber_api_url").value, '/send'), {
							body: JSON.stringify({
								type: 'comment',
								data: {
									"type": 'comment',
									"username": '主人',
									"content": rectxt.replace(/ +/g, ""),
								}
							}),
							headers: {
								'Content-Type': 'application/json'
							},
							method: 'POST'
						});
					}
					
					if (is_final) {
						waitSpeakingEnd();
					}
				}
			}
		}
		else {
			// 只有在有文本内容时才添加到结果中
			if (rectxt && rectxt.trim().length > 0) {
				rec_text = rec_text + rectxt;
			}
		}
		
		var varArea = document.getElementById('varArea');
		// 过滤特殊字符
		rec_text = rec_text.replace(/<[^>]*>/g, '');
		varArea.value = rec_text;
	} catch (error) {
		console.error("处理识别结果时出错:", error);
		info_div.innerHTML = "处理识别结果时出错，请重试";
	}
}

// 连接状态响应
function getConnState(connState) {
	if (connState === 0) { //on open


		info_div.innerHTML = '连接成功!请点击开始';
		if (isfilemode == true) {
			info_div.innerHTML = '请耐心等待,大文件等待时间更长';
			start_file_send();
		}
		else {
			btnStart.disabled = false;
			btnStop.disabled = true;
			btnConnect.disabled = true;
		}
	} else if (connState === 1) {
		//stop();
	} else if (connState === 2) {
		stop();
		console.log('connecttion error');

		alert("连接地址" + document.getElementById('wssip').value + "失败,请检查asr地址和端口。或试试界面上手动授权，再连接。");
		btnStart.disabled = true;
		btnStop.disabled = true;
		btnConnect.disabled = false;

		info_div.innerHTML = '请点击连接';
	}
}

function record() {
	rec.open(function () {
		rec.start();
		console.log("开始");
		btnStart.disabled = true;
		btnStop.disabled = false;
		btnConnect.disabled = true;
	});
}

// 识别启动、停止、清空操作
function start() {
	// 清除显示
	clear();
	//控件状态更新
	console.log("isfilemode" + isfilemode);

	//启动连接
	var ret = wsconnecter.wsStart();
	// 1 is ok, 0 is error
	if (ret == 1) {
		info_div.innerHTML = "正在连接asr服务器，请等待...";
		isRec = true;
		btnStart.disabled = true;
		btnStop.disabled = true;
		btnConnect.disabled = true;

		return 1;
	}
	else {
		info_div.innerHTML = "请点击开始";
		btnStart.disabled = true;
		btnStop.disabled = true;
		btnConnect.disabled = false;

		return 0;
	}
}


function stop() {
	console.log("Stopping, file mode:", isfilemode);
	
	var chunk_size = new Array(5, 10, 5);
	var request = {
		"chunk_size": chunk_size,
		"wav_name": isfilemode ? file_ext : "h5",
		"is_speaking": false,
		"chunk_interval": 10,
		"mode": getAsrMode(),
		"url": document.getElementById('audio_record').src,
	};
	
	// 添加文件特定的信息
	if (isfilemode) {
		request.wav_format = file_ext.toUpperCase();
		if (file_ext.toLowerCase() === "wav") {
			request.audio_fs = file_sample_rate;
		}
	}
	
	console.log("Sending stop request:", request);
	
	// 确保所有剩余数据都被发送
	if (sampleBuf && sampleBuf.length > 0) {
		console.log("Sending remaining data, length:", sampleBuf.length);
		wsconnecter.wsSend(sampleBuf);
		sampleBuf = isfilemode ? new Uint8Array() : new Int16Array();
	}
	
	// 发送停止请求
	wsconnecter.wsSend(JSON.stringify(request));

	// 控件状态更新
	isRec = false;
	info_div.innerHTML = "发送完数据,请等候,正在识别...";

	if (isfilemode == false) {
		btnStop.disabled = true;
		btnStart.disabled = true;
		btnConnect.disabled = true;
		//wait 3s for asr result
		setTimeout(function () {
			console.log("call stop ws!");
			wsconnecter.wsStop();
			btnConnect.disabled = false;
			info_div.innerHTML = "请点击连接";
		}, 3000);

		rec.stop(function (blob, duration) {
			console.log(blob);
			var audioBlob = Recorder.pcm2wav(data = { sampleRate: 16000, bitRate: 16, blob: blob },
				function (theblob, duration) {
					console.log(theblob);
					var audio_record = document.getElementById('audio_record');
					audio_record.src = (window.URL || webkitURL).createObjectURL(theblob);
					audio_record.controls = true;
					//audio_record.play(); 
				}, function (msg) {
					console.log(msg);
				}
			);
		}, function (errMsg) {
			console.log("errMsg: " + errMsg);
		});
	}
	// 停止连接
}

function clear() {
	var varArea = document.getElementById('varArea');

	varArea.value = "";
	rec_text = "";
	offline_text = "";
}

function recProcess(buffer, powerLevel, bufferDuration, bufferSampleRate, newBufferIdx, asyncEnd) {
	if (isRec === true) {
		var data_48k = buffer[buffer.length - 1];

		var array_48k = new Array(data_48k);
		var data_16k = Recorder.SampleData(array_48k, bufferSampleRate, 16000).data;

		sampleBuf = Int16Array.from([...sampleBuf, ...data_16k]);
		var chunk_size = 960; // for asr chunk_size [5, 10, 5]
		info_div.innerHTML = "" + bufferDuration / 1000 + "s";
		while (sampleBuf.length >= chunk_size) {
			sendBuf = sampleBuf.slice(0, chunk_size);
			sampleBuf = sampleBuf.slice(chunk_size, sampleBuf.length);
			wsconnecter.wsSend(sendBuf);
		}
	}
}

function getUseITN() {
	var obj = document.getElementsByName("use_itn");
	for (var i = 0; i < obj.length; i++) {
		if (obj[i].checked) {
			return obj[i].value === "true";
		}
	}
	return false;
}
