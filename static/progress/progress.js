function stringToPercent(num){
    return Math.round(parseFloat(num) * 100);
}

function createDialog(){
    return $( "#dialog-modal" ).dialog({
        height: 220,
        width: 370,
        modal: true,
        dialogClass: 'bar-dialog',
        position: 'top',
        resizable: false,
        closeOnEscape: false,
        open: function(event, ui) {
            $(".ui-dialog-titlebar-close", dialog).hide();
        }
    });
}

function initBars(){
    $("#pb1").progressBar();
    $("#pb2").progressBar();
//    $("#pb3").progressBar();
//    $("#pb4").progressBar();
}

function updateBars(dialog, userID){
    $.get("/cache?userID=" + userID, function(data){
        var progress = JSON.parse(data);
        $('#pb1').progressBar(stringToPercent(progress["fetch_progress"]));
        $('#pb2').progressBar(stringToPercent(progress["graph_progress"]));
//        $('#pb3').progressBar(stringToPercent(progress["edges_progress"]));
//        $('#pb4').progressBar(stringToPercent(progress["ratio_progress"]));

        if (!progress["isRunning"]){
            dialog.dialog("close");
            top.location.href = "https://apps.facebook.com/111880875607873/";
        }
    });
}