// Used for session timeout extending when filling out the form which has this 
// asset reference. Add this to the appropriate forms templates:
//
// {% asset "ckanext-datavicmain/datavicmain-session" %}

$(function () {
    $('form').on('click keyup', function (e) {
        $.ajax(
            {
                url: "/ajax/session",
                cache: false
            }
        );
    });
});