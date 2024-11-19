const util = {
    isFloat: (val) => {
        const floatRegex = /^-?\d+(?:[.,]\d*?)?$/;
        if (!floatRegex.test(val)) {
            return false;
        }

        return !isNaN(parseFloat(val));
    },
    isInt: (val) => {
        const intRegex = /^\d+?$/;
        if (!intRegex.test(val)) {
            return false;
        }

        return !isNaN(parseInt(val));
    }
};
export default util;
