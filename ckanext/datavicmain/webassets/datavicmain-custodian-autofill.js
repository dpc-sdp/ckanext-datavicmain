this.ckan.module('datavicmain-custodian-autofill', function ($) {
    'use strict';
    return {
        options: {
            "default_value": null,
        },
        initialize: function () {
            if ($('.stage-1')[0] && !this.el.val()) {
                this.el.val(this.options.default_value)
            }
        },
    };
});
