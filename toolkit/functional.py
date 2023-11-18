"""Most frequently used formulas in quantitative finance.

Functions are all vectorized and work for both Series and DataFrame.

Accept both time series of prices or returns as the input.
"""
from functools import wraps
import numpy as np
import scipy
import pandas as pd
import statsmodels.api as sm

# Constant used for annualizing returns and volatilities
PERIODICITY = {"D": 365, "B": 252, "W": 52, "M": 12, "Q": 4, "A": 1}


def periodicity(timeseries: pd.Series | pd.DataFrame) -> int:
    """Get the number of periods that make up a year.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Time series of returns or prices

    Returns
    -------
    int
        Number of periods in a year
    """
    return PERIODICITY[timeseries.index.freqstr[0]]


def price_to_return(timeseries: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Convert prices to returns.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Time series of prices

    Returns
    -------
    pd.Series | pd.DataFrame
        Time series of returns
    """
    freq = timeseries.index.freqstr
    s = timeseries.pct_change(fill_method=None)
    # PeriodDtype[B] is deprecated
    s.index = timeseries.index.to_period("D" if freq == "B" else freq)
    return s.iloc[1:]


def return_to_price(timeseries: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Convert returns to prices.

    Initial price is 1.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Time series of returns

    Returns
    -------
    pd.Series | pd.DataFrame
        Time series of prices
    """
    if isinstance(timeseries, pd.Series):
        s = pd.concat([pd.Series([0]), timeseries])
    else:
        s = pd.concat(
            [
                pd.DataFrame(
                    np.zeros((1, timeseries.shape[1])), columns=timeseries.columns
                ),
                timeseries,
            ]
        )
    s.index = pd.date_range(
        end=timeseries.index[-1].to_timestamp(how="e").date(),
        periods=len(timeseries.index) + 1,
        freq=timeseries.index.freq,
    )
    return (s + 1).cumprod()


##############
# Decorators #
##############


def _requirereturn(func):
    """Decorator that convert prices to returns if Index is DatetimeIndex
    """
    @wraps(func)
    def wrapper(pre, *args, **kwargs):
        post = pre
        if isinstance(pre.index, pd.DatetimeIndex):
            post = price_to_return(pre)
        return func(post, *args, **kwargs)

    wrapper.__doc__ = func.__doc__
    return wrapper


def _requireprice(func):
    """Decorator that convert returns to prices if Index is PeriodIndex
    """
    @wraps(func)
    def wrapper(pre, *args, **kwargs):
        post = pre
        if isinstance(pre.index, pd.PeriodIndex):
            post = return_to_price(pre)
        return func(post, *args, **kwargs)

    wrapper.__doc__ = func.__doc__
    return wrapper


def _requirebenchmark(func):
    """Decorator that convert benchmark values to returns if Index is
    DatetimeIndex
    """
    @wraps(func)
    def wrapper(x, pre, *args, **kwargs):
        post = pre
        if isinstance(pre.index, pd.DatetimeIndex):
            post = price_to_return(pre)
        return func(x, post, *args, **kwargs)

    return wrapper


def convert_fx(
    timeseries: pd.Series | pd.DataFrame, foreign: pd.Series, domestic: pd.Series
) -> pd.Series | pd.DataFrame:
    """Convert the time series from foreign currency to domestic currency.

    Note
    ----
    Yahoo always use direct quote.
    (vs Bloomberg use indirect quote for GBP/EUR/AUD/NZD)

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Time series of asset(s). It can be a Series or DataFrame of either
        prices or returns, but not a mix of both.
    foreign : pd.Series
        Foreign currency, which the currency that the asset is denominated
    domestic : pd.Series
        Domestic currency, which is the currency of the investor's home country

    Returns
    -------
    pd.Series | pd.DataFrame
        Time series of the prices
    """
    if (
        isinstance(timeseries.index, type(foreign.index))
        and isinstance(timeseries.index, type(domestic.index))
        and periodicity(timeseries) <= periodicity(foreign)
        and periodicity(timeseries) <= periodicity(domestic)
    ):
        if isinstance(timeseries.index, pd.DatetimeIndex):
            # Price
            # If no FX is quoted on a particular day, filled with the last quoted price
            _fc = foreign.reindex(timeseries.index).ffill()
            _lc = domestic.reindex(timeseries.index).ffill()
            return timeseries.div(_fc, axis=0).mul(_lc, axis=0)
        else:
            # Return
            return convert_fx(
                return_to_price(timeseries),
                return_to_price(foreign),
                return_to_price(domestic),
            )
    else:
        # Error converting, returning original
        return timeseries


@_requirereturn
def compound_return(
    timeseries: pd.Series | pd.DataFrame, annualize=False
) -> float | pd.Series:
    """Compound return of time series

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns
    annualize : bool, optional
        Annualizing the compound return, by default False

    Returns
    -------
    float | pd.Series
        Compound return(s)
    """
    r = np.exp(np.log1p(timeseries).sum(min_count=1))
    if annualize:
        r **= periodicity(timeseries) / len(timeseries)
    return r - 1


@_requirereturn
def arithmetic_mean(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Arithmetic mean of returns

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns

    Returns
    -------
    float | pd.Series
        Arithmetic mean(s) of returns
    """
    return timeseries.mean()


@_requirereturn
def geometric_mean(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Geometric mean of returns

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns

    Returns
    -------
    float | pd.Series
        Geometric mean(s) of returns
    """
    return (compound_return(timeseries, False) + 1) ** (1 / len(timeseries)) - 1


@_requirereturn
def mean_abs_dev(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Mean absolute deviation (or mean deviation) of returns

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns

    Returns
    -------
    float | pd.Series
        Mean absolute deviation of returns
    """
    mean = timeseries.mean()
    return np.absolute(timeseries - mean).sum() / len(timeseries)


@_requirereturn
def variance(
    timeseries: pd.Series | pd.DataFrame, annualize: bool = False
) -> float | pd.Series:
    """Sample variance of returns with Bessel's correction
    (i.e. divide by N-1 instead of N)

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns
    annualize : bool, optional
        Specify if variance should be annualized, by default False

    Returns
    -------
    float | pd.Series
        Variance
    """
    v = timeseries.var()
    if annualize:
        v *= periodicity(timeseries)
    return v


@_requirereturn
def volatility(timeseries: pd.Series | pd.DataFrame, annualize=False):
    """Sample volatility of returns with Bessel's correction
    (i.e. divide by N-1 instead of N)

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns
    annualize : bool, optional
        Specify if volatility should be annualized, by default False

    Returns
    -------
    float | pd.Series
        Volatility
    """
    # Degree of freedom is N-1 for Pandas but N for NumPy
    v = timeseries.std()
    if annualize:
        v *= np.sqrt(periodicity(timeseries))
    return v


@_requirereturn
def skew(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Sample skewness of returns, normalized by N-1

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns

    Returns
    -------
    float | pd.Series
        Skewness
    """
    # Degree of freedom is N-1 for Pandas but N for NumPy
    return timeseries.skew()


@_requirereturn
def kurt(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Sample excess kurtosis, normalized by N-1

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of returns

    Returns
    -------
    float | pd.Series
        Excess kurtosis
    """
    # Excess kurtosis, SciPy does not correct for bias by default
    return timeseries.kurt()


@_requirereturn
def covariance(timeseries: pd.DataFrame, annualize=False) -> pd.DataFrame:
    """Coveriance matrix

    Parameters
    ----------
    timeseries : pd.DataFrame
        DataFrame of returns
    annualize : bool, optional
        Specify if the coveriance matrix is annualized, by default False

    Returns
    -------
    pd.DataFrame
        Coveriance matrix
    """
    cov = timeseries.cov()
    if annualize:
        cov *= periodicity(timeseries)
    return cov


@_requirereturn
def correlation(timeseries: pd.DataFrame) -> pd.DataFrame:
    """Correlation matrix

    Parameters
    ----------
    timeseries : pd.DataFrame
        DataFrame of returns

    Returns
    -------
    pd.DataFrame
        Correlation matrix
    """
    return timeseries.corr()


@_requirereturn
def sharpe(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0, annualize=True
) -> float | pd.Series:
    rate = rfr_annualized
    if not annualize:
        rate = (1 + rfr_annualized) ** (1 / periodicity(timeseries))
    return (compound_return(timeseries, annualize) - rate) / volatility(
        timeseries, annualize
    )


# FIXME not tested @requirePrice
def max_upturn(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    return (timeseries / timeseries.cummin()).max()


@_requireprice
def worst_drawdown(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """Worst drawdown

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of prices

    Returns
    -------
    float | pd.Series
        The worst drawdown which is always a negative number
    """
    return (timeseries / timeseries.cummax()).min() - 1


@_requireprice
def all_drawdown(timeseries: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """All drawdowns, sorted in descending order of magnitude

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        Series or DataFrame of prices

    Returns
    -------
    pd.Series | pd.DataFrame
        Series or DataFrame of drawdowns
    """
    # Drawdown must be calculated for each series individually
    if isinstance(timeseries, pd.DataFrame):
        return timeseries.aggregate(all_drawdown)
    m = timeseries.cummax()
    peak = (timeseries == m) & (timeseries < m).shift(-1)
    num = peak.cumsum()
    dd = timeseries.groupby(num).aggregate(worst_drawdown)
    return dd[dd < 0].sort_values()


@_requirereturn
def avg_annual_drawdown(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    return timeseries.groupby(timeseries.index.year).aggregate(worst_drawdown).mean()


def avg_drawdown(timeseries: pd.Series | pd.DataFrame, d: int = 3) -> float | pd.Series:
    # Average drawdown must be calculated for each series individually
    if isinstance(timeseries, pd.DataFrame):
        return timeseries.aggregate(lambda s: avg_drawdown(s, 3))
    return all_drawdown(timeseries)[:d].mean()


def calmar(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0
) -> float | pd.Series:
    return (compound_return(timeseries, True) - rfr_annualized) / -worst_drawdown(
        timeseries
    )


def sterling(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    return compound_return(timeseries, True) / np.absolute(
        avg_annual_drawdown(timeseries) - 0.1
    )


def sterling_modified(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0, d: int = 3
) -> float | pd.Series:
    return (compound_return(timeseries, True) - rfr_annualized) / np.absolute(
        avg_drawdown(timeseries, d)
    )


def sterling_calmar(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0
) -> float | pd.Series:
    return (compound_return(timeseries, True) - rfr_annualized) / -avg_annual_drawdown(
        timeseries
    )


@_requirereturn
def drawdown_deviation(
    timeseries: pd.Series | pd.DataFrame, d: int = 3
) -> float | pd.Series:
    """Drawdown deviation measures the standard deviation of individual
    drawdowns. This is used the denominator of the Modified Burke ratio.

    Note: This is not the same as downside deviation.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    d : int, optional
        _description_, by default 3

    Returns
    -------
    float | pd.Series
        _description_
    """
    return -np.sqrt((all_drawdown(timeseries)[:d] ** 2).sum() / (len(timeseries)))


def burke_modified(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0, d: int = 3
) -> float | pd.Series:
    """Modified Burke ratio is a Sharpe-like ratio but uses drawdown deviation
    in the denominator.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    rfr_annualized : float, optional
        _description_, by default 0
    d : int, optional
        _description_, by default 3

    Returns
    -------
    float | pd.Series
        _description_
    """
    return (compound_return(timeseries, True) - rfr_annualized) / -drawdown_deviation(
        timeseries, d
    )


@_requireprice
def underwater(timeseries: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    return timeseries / timeseries.cummax() - 1


@_requirereturn
# Positive
def ulcer_index(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """The ulcer index is similar to drawdown deviation but also take into
    account the time being underwater.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_

    Returns
    -------
    float | pd.Series
        _description_
    """
    return np.sqrt((underwater(timeseries) ** 2).sum() / len(timeseries))


@_requirereturn
# Positive
def pain_index(timeseries: pd.Series | pd.DataFrame) -> float | pd.Series:
    """The pain index is similar to the ulcer index but use absolute value of
    the underwater instead of squaring.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_

    Returns
    -------
    float | pd.Series
        _description_
    """
    return np.absolute(underwater(timeseries)).sum() / len(timeseries)


def martin(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0
) -> float | pd.Series:
    """Martin ratio is a Sharpe-like ratio but uses the ulcer index in the
    denominator.

    Also know as ulcer performance index.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    rfr_annualized : float, optional
        _description_, by default 0

    Returns
    -------
    float | pd.Series
        _description_
    """
    return (compound_return(timeseries, True) - rfr_annualized) / ulcer_index(
        timeseries
    )


def pain(
    timeseries: pd.Series | pd.DataFrame, rfr_annualized: float = 0
) -> float | pd.Series:
    """The pain ratio is a Sharpe-like ratio but uses the pain index in the
    denominator.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    rfr_annualized : float, optional
        _description_, by default 0

    Returns
    -------
    float | pd.Series
        _description_
    """
    return (compound_return(timeseries, True) - rfr_annualized) / pain_index(timeseries)


@_requirereturn
def downside_potential(
    timeseries: pd.Series | pd.DataFrame, mar: float = 0
) -> float | pd.Series:
    return (mar - timeseries[timeseries < mar]).sum() / len(timeseries)


@_requirereturn
def upside_potential(
    timeseries: pd.Series | pd.DataFrame, mar: float = 0
) -> float | pd.Series:
    return (timeseries[timeseries > mar] - mar).sum() / len(timeseries)


@_requirereturn
def downside_risk(
    timeseries: pd.Series | pd.DataFrame,
    mar: float = 0,
    annualize: bool = False,
    ddof: int = 0,
) -> float | pd.Series:
    """Downside Risk measures the variability of underperformance below a
    minimum target return. It is the denominator of a Sortino ratio.

    Also know as Downside Deviation.


    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    mar : float, optional
        _description_, by default 0
    annualize : bool, optional
        _description_, by default False
    ddof: int, optional
        Delta Degrees of Freedom, by default 0

    Returns
    -------
    float | pd.Series
        _description_
    """
    dr = np.sqrt(
        ((mar - timeseries[timeseries < mar]) ** 2).sum() / (len(timeseries) - ddof)
    )
    if annualize:
        dr *= np.sqrt(periodicity(timeseries))
    return dr


@_requirereturn
def upside_risk(
    timeseries: pd.Series | pd.DataFrame,
    mar: float = 0,
    annualize: bool = False,
    ddof: int = 0,
) -> float | pd.Series:
    """_summary_

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    mar : float, optional
        _description_, by default 0
    annualize : bool, optional
        _description_, by default False
    ddof : int, optional
        Delta Degrees of Freedom, by default 0

    Returns
    -------
    float | pd.Series
        _description_
    """
    ur = np.sqrt(((timeseries[timeseries > mar] - mar) ** 2).sum() / len(timeseries))
    if annualize:
        ur *= np.sqrt(periodicity(timeseries))
    return ur


def omega(timeseries: pd.Series | pd.DataFrame, mar: float = 0) -> float:
    """Omega ratio measures the gain-loss ratio, i.e. Upside potential divided
    by Downside potential.

    Parameters
    ----------
    timeseries : pd.Series | pd.DataFrame
        _description_
    mar : float, optional
        _description_, by default 0

    Returns
    -------
    float
        _description_
    """
    return upside_potential(timeseries, mar) / downside_potential(timeseries, mar)


def sortino(
    timeseries: pd.Series | pd.DataFrame, mar: float = 0, ddof: int = 0
) -> float | pd.Series:
    ann_mar = (1 + mar) ** periodicity(timeseries) - 1
    return (compound_return(timeseries, annualize=True) - ann_mar) / downside_risk(
        timeseries, mar, annualize=True, ddof=ddof
    )


def upside_potential_ratio(
    timeseries: pd.Series | pd.DataFrame, mar: float = 0
) -> float | pd.Series:
    return upside_potential(timeseries, mar) / downside_risk(
        timeseries, mar, annualize=True
    )


def variability_skewness(
    timeseries: pd.Series | pd.DataFrame, mar: float = 0
) -> float | pd.Series:
    """Variability skewness is the ratio of Upside risk compared to Downside
    risk.

    Parameters
    ----------
    s : pd.Series | pd.DataFrame
        _description_
    mar : float, optional
        _description_, by default 0

    Returns
    -------
    float | pd.Series
        _description_
    """
    return upside_risk(timeseries, mar) / downside_risk(timeseries, mar)


# Additional


@_requirereturn
def best_period(timeseries: pd.Series) -> float:
    return timeseries.max()


@_requirereturn
def worst_period(timeseries: pd.Series) -> float:
    return timeseries.min()


@_requirereturn
def avg_pos(timeseries: pd.Series) -> float:
    return timeseries[timeseries >= 0].mean()


@_requirereturn
def avg_neg(timeseries: pd.Series) -> float:
    return timeseries[timeseries < 0].mean()


@_requirereturn
def vol_pos(timeseries: pd.Series) -> float:
    return timeseries[timeseries >= 0].std()


@_requirereturn
def vol_neg(timeseries: pd.Series) -> float:
    return timeseries[timeseries < 0].std()


#########################
# Relative to benchmark #
#########################
# Benchmark is already net of risk-free rate
# If risk-free rate is yet to substract from s, you must supply the rfr_periodic


@_requirereturn
@_requirebenchmark
# f, b -> Series of shape (3,) (float, float, float)
# f, bb -> Series of shape (3,) (float, Series, float)
# ff, b -> DataFrame of shape (3, n)
# ff, bb -> DataFrame of shape (3, n), the middle row is Series
# where n is the number of assets (column) in s
def regress(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    rfr_periodic: float | pd.Series = 0,
) -> pd.Series | pd.DataFrame:
    if isinstance(timeseries, pd.DataFrame):
        return timeseries.aggregate(lambda x: regress(x, benchmark, rfr_periodic))
    result = sm.OLS(timeseries - rfr_periodic, sm.add_constant(benchmark)).fit()
    alpha = result.params.iloc[0]
    betas = result.params.iloc[1:].squeeze()  # Series
    r2 = result.rsquared
    r2adj = result.rsquared_adj
    return pd.Series([alpha, betas, r2, r2adj], index=["alpha", "betas", "r2", "r2adj"])


@_requirereturn
@_requirebenchmark
def beta(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    rfr_periodic: float | pd.Series = 0,
) -> float | pd.Series | pd.DataFrame:
    # series & series -> float
    # series & benchmark(, m) -> Series(m,)
    # fund(, k) & series -> Series(, k)
    # fund(, k) & benchmark(, m) -> Series(k,) with the 2nd row being another Series(m,)
    # Note: benchmark should be already NET of risk-free rate, so this method works for multi-factor analysis
    return regress(timeseries, benchmark, rfr_periodic).iloc[1]


@_requirereturn
@_requirebenchmark
def alpha(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    rfr_periodic: float | pd.Series = 0,
    annualize=False,
) -> float | pd.Series | pd.DataFrame:
    a = regress(timeseries, benchmark, rfr_periodic).iloc[0]
    if annualize:
        # Sharpe's definition
        a *= periodicity(timeseries)
    return a


@_requirereturn
@_requirebenchmark
# FIXME: add test case
def rsquared(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    rfr_periodic: float | pd.Series = 0,
    adjusted: bool = False,
) -> float | pd.Series | pd.DataFrame:
    result = regress(timeseries, benchmark, rfr_periodic)
    return result.iloc[3] if adjusted else result.iloc[2]


@_requirereturn
@_requirebenchmark
# Unlike pure beta, it doens't make sense to calcualte bull/bear beta on multiple indices, so benchmark must not be a DataFrame
def bull_beta(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series,
    rfr_periodic: float | pd.Series = 0,
) -> float | pd.Series | pd.DataFrame:
    bull = benchmark > rfr_periodic
    return beta(
        timeseries[bull].subtract(rfr_periodic[bull], axis=0),
        benchmark[bull].subtract(rfr_periodic[bull], axis=0),
    )


@_requirereturn
@_requirebenchmark
def bear_beta(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series,
    rfr_periodic: float | pd.Series = 0,
) -> float | pd.Series | pd.DataFrame:
    bear = benchmark < rfr_periodic
    return beta(
        timeseries[bear].subtract(rfr_periodic[bear], axis=0),
        benchmark[bear].subtract(rfr_periodic[bear], axis=0),
    )


def beta_timing_ratio(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    rfr_periodic: float | pd.Series = 0,
) -> float | pd.Series | pd.DataFrame:
    return bull_beta(timeseries, benchmark, rfr_periodic) / bear_beta(
        timeseries, benchmark, rfr_periodic
    )


# Only one benchmark


def treynor(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series,
    rfr_periodic: float | pd.Series = 0,
    annualize=True,
) -> float | pd.Series:
    rfr_annualized = compound_return(rfr_periodic, annualize=True)
    return (compound_return(timeseries, annualize) - rfr_annualized) / beta(
        timeseries, benchmark, rfr_periodic
    )


@_requirereturn
@_requirebenchmark
def tracking_error(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    annualize: bool = False,
) -> float | pd.Series:
    return volatility(timeseries.subtract(benchmark, axis=0), annualize)


@_requirereturn
@_requirebenchmark
def active_return(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series | pd.DataFrame,
    annualize=True,
) -> float | pd.Series:
    # Arithmetic
    return compound_return(timeseries, True) - compound_return(benchmark, True)


@_requirereturn
@_requirebenchmark
def information_ratio(
    timeseries: pd.Series | pd.DataFrame, benchmark: pd.Series | pd.DataFrame
) -> float | pd.Series:
    # Arithmetic
    return active_return(timeseries, benchmark, True) / tracking_error(
        timeseries, benchmark, True
    )


@_requirereturn
@_requirebenchmark
def summary(
    timeseries: pd.Series | pd.DataFrame,
    benchmark: pd.Series,
    rfr_periodic,
    mar: float = 0,
):
    rfr_annualized = compound_return(rfr_periodic, annualize=True)
    s_rfr = timeseries.subtract(rfr_periodic, axis=0)
    mkt_rfr = benchmark - rfr_periodic

    sd = {
        "Number of Period": len(timeseries),
        "Frequency": timeseries.index.freqstr,
        "Total Return": compound_return(timeseries),
        "Periodic Mean Return": arithmetic_mean(timeseries),
        "Periodic Geometric Mean": geometric_mean(timeseries),
        "Annualized Return": compound_return(timeseries, annualize=True),
        "Best Period": best_period(timeseries),
        "Worst Period": worst_period(timeseries),
        "Average Positive Period": avg_pos(timeseries),
        "Average Negative Period": avg_neg(timeseries),
        "Mean Absolute Deviation": mean_abs_dev(timeseries),
        "Variance": variance(timeseries),
        "Period Volatility": volatility(timeseries),
        "Period Volatility of Positive Return": vol_pos(timeseries),
        "Period Volatility of Negative Return": vol_neg(timeseries),
        "Annualized Volatility": volatility(timeseries, annualize=True),
        f"Sharpe ({rfr_annualized:.2%})": sharpe(timeseries, rfr_annualized),
        "Skewness": skew(timeseries),
        "Excess Kurtosis": kurt(timeseries),
        # The following are not tested
        "Normal (1%)": is_normal(timeseries, 0.01),
        "VaR Historical (95%)": var_historical(timeseries),
        "VaR Gaussian (95%)": var_normal(timeseries),
        "VaR Modified (95%)": var_modified(timeseries),
        "CVaR Historical (95%)": cvar_historical(timeseries),
        "CVaR Gaussian (95%)": cvar_normal(timeseries),
        # Drawdown
        "Worst Drawdown": worst_drawdown(timeseries),
        "Calmar": calmar(timeseries, rfr_annualized=rfr_annualized),
        "Average Drawdown": avg_drawdown(timeseries, d=3),
        "Sterling Original": sterling(timeseries),  # Not tested
        "Sterling Modified": sterling_modified(
            timeseries, rfr_annualized=rfr_annualized, d=3
        ),
        "Sterling-Calmar": sterling_calmar(timeseries, rfr_annualized=rfr_annualized),
        "Drawdown Deviation": drawdown_deviation(timeseries, d=3),
        "Modified Burke": burke_modified(
            timeseries, rfr_annualized=rfr_annualized, d=3
        ),
        "Average Annual Drawdown": avg_annual_drawdown(timeseries),
        "Pain Index": pain_index(timeseries),
        "Pain Ratio": pain(timeseries, rfr_annualized),
        "Ulcer Index": ulcer_index(timeseries),
        "Martin Ratio": martin(timeseries, rfr_annualized),
        # Partial
        "Downside Potential": downside_potential(timeseries, mar=mar),
        "Downside Risk (Periodic)": downside_risk(timeseries, mar=mar, ddof=1),
        "Downside Risk (Annualized)": downside_risk(
            timeseries, mar=mar, annualize=True, ddof=1
        ),
        "Upside Potential": upside_potential(timeseries, mar=mar),
        "Upside Risk (Periodic)": upside_risk(timeseries, mar=mar, ddof=1),
        "Upside Risk (Annualized)": upside_risk(
            timeseries, mar=mar, annualize=True, ddof=1
        ),
        "Omega Ratio": omega(timeseries, mar=mar),
        "Upside Potential Ratio": upside_potential_ratio(timeseries, mar),
        "Variability Skewness": variability_skewness(timeseries, mar),
        "Sortino Ratio": sortino(timeseries, mar=mar, ddof=1),
        # Relative
        "Tracking Error": tracking_error(timeseries, benchmark),
        "Annualized Tracking Error": tracking_error(timeseries, benchmark, True),
        "Annualized Active Return": active_return(timeseries, benchmark, True),
        "Annualized Information Ratio": information_ratio(timeseries, benchmark),
        # Regression
        "Beta": beta(timeseries, mkt_rfr, rfr_periodic),
        "Alpha (Annualized)": alpha(timeseries, mkt_rfr, rfr_periodic, annualize=True),
        "Correlation": correlation(pd.concat([s_rfr, mkt_rfr], axis=1))
        .iloc[-1, :-1]
        .squeeze(),
        "R-Squared": rsquared(timeseries, mkt_rfr, rfr_periodic),
        # Bull/Bear/Timing not tested
        "Bull Beta": bull_beta(timeseries, benchmark, rfr_periodic),
        "Bear Beta": bear_beta(timeseries, benchmark, rfr_periodic),
        "Beta Timing Ratio": beta_timing_ratio(timeseries, benchmark, rfr_periodic),
        "Treynor Ratio": treynor(timeseries, benchmark, rfr_periodic),
        "Up Capture": up_capture(timeseries, benchmark),
        "Down Capture": down_capture(timeseries, benchmark),
    }
    return sd


# TODO:
# Accept both 5% (Level of significance) or 95% (Confidence Interval)

# FIXME: Not working for dataframe
@_requirereturn
def is_normal(timeseries: pd.Series, a: float = 0.01):
    """Bera‐Jarque statistic.

    The test statistic is always nonnegative.

    If p-value > a means null hypothesis (normal) cannot be rejected.

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    a : float, optional
        Significance level, by default 0.01

    Returns
    -------
    _type_
        _description_
    """
    return scipy.stats.jarque_bera(timeseries)[1] > a


@_requirereturn
def var_historical(timeseries: pd.Series, alpha: float = 0.95) -> float:
    """Historical Value-at-Risk

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    alpha : float, optional
        _description_, by default 0.05

    Returns
    -------
    float
        VaR, reported as a negative number
    """
    a = min(alpha, 1 - alpha)
    return timeseries.quantile(a)


def var_normal(timeseries: pd.Series, alpha: float = 0.95) -> float:
    """Gaussian Value-at-Risk

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    alpha : float, optional
        _description_, by default 0.95

    Returns
    -------
    float
        VaR, reported as a negative number
    """
    z = -abs(scipy.stats.norm.ppf(alpha))
    mu = arithmetic_mean(timeseries)
    sigma = volatility(timeseries, annualize=False)
    return mu + sigma * z


def var_modified(timeseries: pd.Series, alpha: float = 0.95) -> float:
    """Modified Value-at-Risk

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    alpha : float, optional
        _description_, by default 0.95

    Returns
    -------
    float
        mVaR, reported as a negative number
    """
    z = -abs(scipy.stats.norm.ppf(alpha))
    mu = arithmetic_mean(timeseries)
    sigma = volatility(timeseries, annualize=False)
    S = skew(timeseries)
    K = kurt(timeseries)
    t = (
        z
        + (z**2 - 1) * S / 6
        + (z**3 - 3 * z) * K / 24
        - (2 * z**3 - 5 * z) * S**2 / 36
    )
    return mu + sigma * t


# TODO: Add test case
@_requirereturn
def cvar_historical(timeseries: pd.Series, alpha: float = 0.05):
    """Historical Conditional Value-at-Risk (CVaR).

    Also known as Expected Shortfall (ES).

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    alpha : float, optional
        _description_, by default 0.01

    Returns
    -------
    _type_
        CVaR, reported as a negative number
    """
    return timeseries[timeseries < var_historical(timeseries, alpha)].mean()


# TODO: Add test case


def cvar_normal(timeseries: pd.Series, alpha: float = 0.95, annualize=False):
    """Gaussian Conditional Value-at-Risk (CVaR).

    Also known as Expected Shortfall (ES).

    Parameters
    ----------
    timeseries : pd.Series
        _description_
    alpha : float, optional
        _description_, by default 0.95
    annualize : bool, optional
        _description_, by default False

    Returns
    -------
    _type_
        CVaR, reported as a negative number
    """
    a = min(alpha, 1 - alpha)
    mu = arithmetic_mean(timeseries)
    sigma = volatility(timeseries, annualize)
    return mu - sigma * scipy.stats.norm.pdf(scipy.stats.norm.ppf(a)) / a


@_requirereturn
@_requirebenchmark
def up_capture(
    timeseries: pd.Series | pd.DataFrame, benchmark: pd.Series | pd.DataFrame
):
    up = benchmark >= 0
    return compound_return(timeseries[up]) / compound_return(benchmark[up])


@_requirereturn
@_requirebenchmark
def down_capture(
    timeseries: pd.Series | pd.DataFrame, benchmark: pd.Series | pd.DataFrame
):
    down = benchmark < 0
    return compound_return(timeseries[down]) / compound_return(benchmark[down])


def carino(r, b):
    return np.where(r == b, 1 / (1 + r), (np.log1p(r) - np.log1p(b)) / (r - b))


# TODO:
#   m2, drawdown table
