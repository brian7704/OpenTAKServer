from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField


class MediaMTSGlobalConfig(FlaskForm):
    logLevel = StringField()
    #logDestinations
    logFile = StringField()
    readTimeout = StringField()
    writeTimeout = StringField()
    writeQueueSize = IntegerField()
    udpMaxPayloadSize = IntegerField()
    externalAuthenticationURL = StringField()
    api = BooleanField()
    apiAddress = StringField()
    metrics = BooleanField()
    metricsAddress = StringField()
    pprof = BooleanField()
    pprofAddress = StringField()
    runOnConnect = StringField()
    runOnConnectRestart = BooleanField()
    runOnDisconnect = StringField()
    rtsp = BooleanField()
    #protocols
    encryption = StringField()
    rtspAddress = StringField()
    rtspsAddress = StringField()
    rtpAddress = StringField()
    rtcpAddress = StringField()
    multicastIPRange = StringField()
    multicastRTPPort = IntegerField()
    multicastRTCPPort = IntegerField()
    serverKey = StringField()
    serverCert = StringField()
    #authMethods
    rtmp = BooleanField()
    rtmpAddress = StringField()
    rtmpEncryption = StringField()
    rtmpsAddress = StringField()
    rtmpServerKey = StringField()
    rtmpServerCert = StringField()
    hls = BooleanField()
    hlsAddress = StringField()
    hlsEncryption = BooleanField()
    hlsServerKey = StringField()
    hlsServerCert = StringField()
    hlsAlwaysRemux = BooleanField()
    hlsVariant = StringField()
    hlsSegmentCount = IntegerField()
    hlsSegmentDuration = StringField()
    hlsPartDuration = StringField()
    hlsSegmentMaxSize = StringField()
    hlsAllowOrigin = StringField()
    #hlsTrustedProxies
    hlsDirectory = StringField()
    webrtc = BooleanField()
    webrtcAddress = StringField()
    webrtcEncryption = BooleanField()
    webrtcServerKey = StringField()
    webrtcServerCert = StringField()
    webrtcAllowOrigin = StringField()
    #webrtcTrustedProxies
    webrtcLocalUDPAddress = StringField()
    webrtcLocalTCPAddress = StringField()
    webrtcIPsFromInterfaces = BooleanField()
    #webrtcIPsFromInterfacesList
    #webrtcAdditionalHosts
    #webrtcICEServers2
    srt = BooleanField()
    srtAddress = StringField()

    def serialize(self):
        return_value = {}
        for field in self._fields:
            if field != 'csrf_token':
                return_value[field] = self._fields[field].data
        return return_value
