this.ckan.module('datavicmain-custodian-autofill', function ($) {
    'use strict';
    let userCache = null;
    return {
        options: {
            property: null,
        },
        initialize: function () {
            if ($('.stage-1')[0] && !this.el.val()) {
                this._fillField(this)
            }
        },
        _fillField: async function (e) {
            if (!userCache) {
                userCache = new Promise((ok, fail) => {
                    fetch(this.sandbox.client.call("GET", "user_show", "", data => ok(data.result), fail));
                });
            };
            const user = await userCache;
            this.el.val(user[this.options.property])
        }
    };
});
