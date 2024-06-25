ckan.module("vic-entity-file", function ($, _) {
    "use strict";

    return {
        options: {
            itemId: null
        },
        initialize: function () {
            $.proxyAll(this, /_on/);

            if (!this.options.itemId) {
                console.error("No item ID provided");
                return;
            }

            $(".vic-remove-image").on("click", this._onDeleteImage);
        },

        _onDeleteImage: function (e) {
            console.log('test');

            $.ajax({
                url: this.sandbox.client.url("/api/action/vic_home_remove_item_image"),
                type: "POST",
                data: {
                    id: this.options.itemId
                },
                success: function () {
                    $(".image-preview").children().remove();
                }
            });
        }
    };
});
