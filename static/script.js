const socket = io("https://sonic-sync-78daad0a1d18.herokuapp.com", { transports: ["websocket"] });

var gpsData
var currentUserId //TODO: grab the current user ID somehow

        function distanceCompare(a, b){
            if(a.distance < b.distance){
                return -1
            }else if(a.distance > b.distance){
                return 1
            }else{
                return 0
            }
        }
        socket.on("update_active_users", (activeUsers) => {
            const activeUsersDiv = document.getElementById("active-users");
            activeUsersDiv.innerHTML = "";  // Clear previous entries to avoid duplication
            var location
            activeUsers.forEach((user) => {
                gpsData.forEach((gpsPoint) => {
                    if(gpsPoint.received_user_id == user.user_id){
                        user.gps = gpsPoint
                        if(user.userId == currentUserId){
                            location = gpsPoint
                        }
                    }
                })
            })
            activeUsers.forEach((user) => {
                user.distance = Math.SQRT2s((location.latidude - user.gps.latitude) ** 2 + (location.longitude - user.gps.longitude) ** 2)
            })
            activeUsers.sort(distanceCompare)

            activeUsers.forEach((user) => {

                setInterval(() => {
                    fetchTrackInfo(user.user_id);
                    sendGPSdata();
                }, 5000);
            });
        });

        function fetchTrackInfo(userId) {
            socket.emit('find_tracks', { user_id: userId });
        }

        function updateGPSDisplay(data) {
            const gpsDataDiv = document.getElementById("gps-data");
            gpsDataDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
        }

        function sendGPSdata() {
            socket.emit('send_gps');
        }

        socket.on("update_gps", (data) => {
            updateGPSDisplay(data);
            gpsData = data
        });
        
        socket.on('track_info', (data) => {
        });