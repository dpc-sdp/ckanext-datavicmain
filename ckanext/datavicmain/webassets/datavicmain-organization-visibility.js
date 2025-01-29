this.ckan.module("datavicmain-organization-visibility", function ($) {
    "use strict";

    return {
        options: {},
        initialize: function () {
            if ($("#field-visibility").val() == "unrestricted") {
                $("#field-parent option.restricted").addClass("hide");
                $("#field-parent option:not('.restricted')").removeClass("hide");
            };

            $("#field-visibility[readonly=true]").find("option:not(:selected)").attr("disabled", true);

            $("#field-visibility").on("change", function(e) {
                $("#field-parent").val("");
                $("#select2-chosen-1").text($("#field-parent option[value='']").text());
                if ($(this).val() == "restricted") {
                    $("#field-parent option:not('.restricted')").addClass("hide");
                    $("#field-parent option.restricted").removeClass("hide");
                    $("#field-parent option[value='']").removeClass("hide");
                } else {
                    $("#field-parent option.restricted").addClass("hide");
                    $("#field-parent option:not('.restricted')").removeClass("hide");
                };
            });
        }
    };
})
