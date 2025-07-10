/**
 * Copyright FunASR (https://github.com/alibaba-damo-academy/FunASR). All Rights
 * Reserved. MIT License  (https://opensource.org/licenses/MIT)
 */
/* 2021-2023 by zhaoming,mali aihealthx.com */

function WebSocketConnectMethod(config) { //定义socket连接方法类
	var speechSokt;
	var connKeeperID;

	var msgHandle = config.msgHandle;
	var stateHandle = config.stateHandle;

	this.wsStart = function () {
		var Uri = document.getElementById('wssip').value; //"wss://111.205.137.58:5821/wss/" //设置wss asr online接口地址 如 wss://X.X.X.X:port/wss/
		if (Uri.match(/wss:\S*|ws:\S*/)) {
			console.log("Uri" + Uri);
		}
		else {
			alert("请检查wss地址正确性");
			return 0;
		}

		if ('WebSocket' in window) {
			speechSokt = new WebSocket(Uri, ['binary']); // 定义socket连接对象
			speechSokt.onopen = function (e) { onOpen(e); }; // 定义响应函数
			speechSokt.onclose = function (e) {
				console.log("onclose ws!");
				//speechSokt.close();
				onClose(e);
			};
			speechSokt.onmessage = function (e) { onMessage(e); };
			speechSokt.onerror = function (e) { onError(e); };
			return 1;
		}
		else {
			alert('当前浏览器不支持 WebSocket');
			return 0;
		}
	};

	// 定义停止与发送函数
	this.wsStop = function () {
		if (speechSokt != undefined) {
			console.log("stop ws!");
			speechSokt.close();
		}
	};

	this.wsSend = function (oneData) {

		if (speechSokt == undefined) return;
		if (speechSokt.readyState === 1) { // 0:CONNECTING, 1:OPEN, 2:CLOSING, 3:CLOSED

			speechSokt.send(oneData);


		}
	};

	// SOCEKT连接中的消息与状态响应
	function onOpen(e) {
		// 发送json 
		// 左上下文：用于模型理解前文 。当前帧：本次推理的主音频帧数。 右上下文：用于模型理解后文（流式时一般较小）
		// 实时性要求高：
		// 推荐 [4, 8, 4] 或 [5, 10, 5]，延迟低，适合对话、直播等场景。
		// 准确率优先：短的停顿就不会被切分识别了
		// 推荐 [8, 16, 8] 或 [16, 32, 16]，适合离线转写、会议记录等。
		// 极端低延迟：
		// 可尝试 [1, 8, 1]，但要注意识别准确率下降。
		var chunk_size = new Array(4, 8, 4);
		var request = {
			"chunk_size": chunk_size,
			"wav_name": isfilemode ? file_ext : "h5",
			"is_speaking": true,
			"chunk_interval": 10,
			"itn": getUseITN(),
			"mode": getAsrMode(),
		};
		
		if (isfilemode) {
			// 设置文件特定的处理信息
			request.wav_format = file_ext.toUpperCase();
			if (file_ext.toLowerCase() == "wav") {
				request.wav_format = "PCM";
				request.audio_fs = file_sample_rate;
			}
			// 对于文件模式，强制使用离线识别
			request.mode = "offline";
			console.log("文件上传模式: " + file_ext + ", 采样率: " + file_sample_rate + ", 模式: " + request.mode);
		}

		var hotwords = getHotwords();

		if (hotwords != null) {
			request.hotwords = hotwords;
		}
		console.log(JSON.stringify(request));
		speechSokt.send(JSON.stringify(request));
		console.log("连接成功");
		stateHandle(0);

	}

	function onClose(e) {
		stateHandle(1);
	}

	function onMessage(e) {
		console.log("WebSocket message received:", e.data ? e.data.substring(0, 100) + "..." : "empty");
		msgHandle(e);
	}

	function onError(e) {
		console.error("WebSocket error:", e);
		info_div.innerHTML = "连接错误: " + e;
		stateHandle(2);
	}


}