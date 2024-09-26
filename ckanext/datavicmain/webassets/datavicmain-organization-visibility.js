this.ckan.module("datavicmain-organization-visibility", function ($) {
    "use strict";

    return {
        options: {},
        initialize: function () {
            var selectedOption = $("option[selected=selected]");

            if (selectedOption.hasClass("restricted")) {
                $(".select2-chosen").addClass("restricted");
            };

            $("#field-visibility[readonly=true]").find("option:not(:selected)").attr("disabled", true);

            $("#field-parent").on('change', function (e) {
                var orgName = $("#select2-chosen-1").text();
                var topLevel = "None - top level";

                if ($("#field-parent option:contains('" + orgName + "')").hasClass("restricted")) {
                    $("#select2-chosen-1").addClass("restricted");
                    $("#field-visibility option[value='unrestricted']").attr("selected", false);
                    $("#field-visibility option[value='restricted']").attr("selected", true);
                    $("#field-visibility option[value='unrestricted']").attr("disabled", true);
                    $("#field-visibility option[value='restricted']").attr("disabled", false);
                } else if ($("#select2-chosen-1").text() == topLevel) {
                    $("#select2-chosen-1").removeClass("restricted");
                    $("#field-visibility option[value='unrestricted']").attr("disabled", false);
                    $("#field-visibility option[value='restricted']").attr("disabled", false);
                    $("#field-visibility option[value='restricted']").attr("selected", false);
                    $("#field-visibility option[value='unrestricted']").attr("selected", true);
                } else {
                    $("#select2-chosen-1").removeClass("restricted");
                    $("#field-visibility option[value='restricted']").attr("disabled", true);
                    $("#field-visibility option[value='unrestricted']").attr("disabled", false);
                    $("#field-visibility option[value='restricted']").attr("selected", false);
                    $("#field-visibility option[value='unrestricted']").attr("selected", true);
                }
            });
        }
    }
})
