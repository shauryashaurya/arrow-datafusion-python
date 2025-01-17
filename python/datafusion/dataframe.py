# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
""":py:class:`DataFrame` is one of the core concepts in DataFusion.

See :ref:`user_guide_concepts` in the online documentation for more information.
"""

from __future__ import annotations
import warnings
from typing import (
    Any,
    Iterable,
    List,
    TYPE_CHECKING,
    Literal,
    overload,
    Optional,
    Union,
)
from datafusion.record_batch import RecordBatchStream
from typing_extensions import deprecated
from datafusion.plan import LogicalPlan, ExecutionPlan

if TYPE_CHECKING:
    import pyarrow as pa
    import pandas as pd
    import polars as pl
    import pathlib
    from typing import Callable, Sequence

from datafusion._internal import DataFrame as DataFrameInternal
from datafusion.expr import Expr, SortExpr, sort_or_default
from enum import Enum


# excerpt from deltalake
# https://github.com/apache/datafusion-python/pull/981#discussion_r1905619163
class Compression(Enum):
    """Enum representing the available compression types for Parquet files."""

    UNCOMPRESSED = "uncompressed"
    SNAPPY = "snappy"
    GZIP = "gzip"
    BROTLI = "brotli"
    LZ4 = "lz4"
    # lzo is not implemented yet
    # https://github.com/apache/arrow-rs/issues/6970
    # LZO = "lzo"
    ZSTD = "zstd"
    LZ4_RAW = "lz4_raw"

    @classmethod
    def from_str(cls, value: str) -> "Compression":
        """Convert a string to a Compression enum value.

        Args:
            value: The string representation of the compression type.

        Returns:
            The Compression enum lowercase value.

        Raises:
            ValueError: If the string does not match any Compression enum value.
        """
        try:
            return cls(value.lower())
        except ValueError:
            raise ValueError(
                f"{value} is not a valid Compression. Valid values are: {[item.value for item in Compression]}"
            )

    def get_default_level(self) -> Optional[int]:
        """Get the default compression level for the compression type.

        Returns:
            The default compression level for the compression type.
        """
        # GZIP, BROTLI default values from deltalake repo
        # https://github.com/apache/datafusion-python/pull/981#discussion_r1905619163
        # ZSTD default value from delta-rs
        # https://github.com/apache/datafusion-python/pull/981#discussion_r1904789223
        if self == Compression.GZIP:
            return 6
        elif self == Compression.BROTLI:
            return 1
        elif self == Compression.ZSTD:
            return 4
        return None


class DataFrame:
    """Two dimensional table representation of data.

    See :ref:`user_guide_concepts` in the online documentation for more information.
    """

    def __init__(self, df: DataFrameInternal) -> None:
        """This constructor is not to be used by the end user.

        See :py:class:`~datafusion.context.SessionContext` for methods to
        create a :py:class:`DataFrame`.
        """
        self.df = df

    def __getitem__(self, key: str | List[str]) -> DataFrame:
        """Return a new :py:class`DataFrame` with the specified column or columns.

        Args:
            key: Column name or list of column names to select.

        Returns:
            DataFrame with the specified column or columns.
        """
        return DataFrame(self.df.__getitem__(key))

    def __repr__(self) -> str:
        """Return a string representation of the DataFrame.

        Returns:
            String representation of the DataFrame.
        """
        return self.df.__repr__()

    def _repr_html_(self) -> str:
        return self.df._repr_html_()

    def describe(self) -> DataFrame:
        """Return the statistics for this DataFrame.

        Only summarized numeric datatypes at the moments and returns nulls
        for non-numeric datatypes.

        The output format is modeled after pandas.

        Returns:
            A summary DataFrame containing statistics.
        """
        return DataFrame(self.df.describe())

    def schema(self) -> pa.Schema:
        """Return the :py:class:`pyarrow.Schema` of this DataFrame.

        The output schema contains information on the name, data type, and
        nullability for each column.

        Returns:
            Describing schema of the DataFrame
        """
        return self.df.schema()

    @deprecated(
        "select_columns() is deprecated. Use :py:meth:`~DataFrame.select` instead"
    )
    def select_columns(self, *args: str) -> DataFrame:
        """Filter the DataFrame by columns.

        Returns:
            DataFrame only containing the specified columns.
        """
        return self.select(*args)

    def select(self, *exprs: Expr | str) -> DataFrame:
        """Project arbitrary expressions into a new :py:class:`DataFrame`.

        Args:
            exprs: Either column names or :py:class:`~datafusion.expr.Expr` to select.

        Returns:
            DataFrame after projection. It has one column for each expression.

        Example usage:

        The following example will return 3 columns from the original dataframe.
        The first two columns will be the original column ``a`` and ``b`` since the
        string "a" is assumed to refer to column selection. Also a duplicate of
        column ``a`` will be returned with the column name ``alternate_a``::

            df = df.select("a", col("b"), col("a").alias("alternate_a"))

        """
        exprs_internal = [
            Expr.column(arg).expr if isinstance(arg, str) else arg.expr for arg in exprs
        ]
        return DataFrame(self.df.select(*exprs_internal))

    def drop(self, *columns: str) -> DataFrame:
        """Drop arbitrary amount of columns.

        Args:
            columns: Column names to drop from the dataframe.

        Returns:
            DataFrame with those columns removed in the projection.
        """
        return DataFrame(self.df.drop(*columns))

    def filter(self, *predicates: Expr) -> DataFrame:
        """Return a DataFrame for which ``predicate`` evaluates to ``True``.

        Rows for which ``predicate`` evaluates to ``False`` or ``None`` are filtered
        out.  If more than one predicate is provided, these predicates will be
        combined as a logical AND. If more complex logic is required, see the
        logical operations in :py:mod:`~datafusion.functions`.

        Args:
            predicates: Predicate expression(s) to filter the DataFrame.

        Returns:
            DataFrame after filtering.
        """
        df = self.df
        for p in predicates:
            df = df.filter(p.expr)
        return DataFrame(df)

    def with_column(self, name: str, expr: Expr) -> DataFrame:
        """Add an additional column to the DataFrame.

        Args:
            name: Name of the column to add.
            expr: Expression to compute the column.

        Returns:
            DataFrame with the new column.
        """
        return DataFrame(self.df.with_column(name, expr.expr))

    def with_columns(
        self, *exprs: Expr | Iterable[Expr], **named_exprs: Expr
    ) -> DataFrame:
        """Add columns to the DataFrame.

        By passing expressions, iteratables of expressions, or named expressions. To
        pass named expressions use the form name=Expr.

        Example usage: The following will add 4 columns labeled a, b, c, and d::

            df = df.with_columns(
                lit(0).alias('a'),
                [lit(1).alias('b'), lit(2).alias('c')],
                d=lit(3)
                )

        Args:
            exprs: Either a single expression or an iterable of expressions to add.
            named_exprs: Named expressions in the form of ``name=expr``

        Returns:
            DataFrame with the new columns added.
        """

        def _simplify_expression(
            *exprs: Expr | Iterable[Expr], **named_exprs: Expr
        ) -> list[Expr]:
            expr_list = []
            for expr in exprs:
                if isinstance(expr, Expr):
                    expr_list.append(expr.expr)
                elif isinstance(expr, Iterable):
                    for inner_expr in expr:
                        expr_list.append(inner_expr.expr)
                else:
                    raise NotImplementedError
            if named_exprs:
                for alias, expr in named_exprs.items():
                    expr_list.append(expr.alias(alias).expr)
            return expr_list

        expressions = _simplify_expression(*exprs, **named_exprs)

        return DataFrame(self.df.with_columns(expressions))

    def with_column_renamed(self, old_name: str, new_name: str) -> DataFrame:
        r"""Rename one column by applying a new projection.

        This is a no-op if the column to be renamed does not exist.

        The method supports case sensitive rename with wrapping column name
        into one the following symbols (" or ' or \`).

        Args:
            old_name: Old column name.
            new_name: New column name.

        Returns:
            DataFrame with the column renamed.
        """
        return DataFrame(self.df.with_column_renamed(old_name, new_name))

    def aggregate(
        self, group_by: list[Expr] | Expr, aggs: list[Expr] | Expr
    ) -> DataFrame:
        """Aggregates the rows of the current DataFrame.

        Args:
            group_by: List of expressions to group by.
            aggs: List of expressions to aggregate.

        Returns:
            DataFrame after aggregation.
        """
        group_by = group_by if isinstance(group_by, list) else [group_by]
        aggs = aggs if isinstance(aggs, list) else [aggs]

        group_by = [e.expr for e in group_by]
        aggs = [e.expr for e in aggs]
        return DataFrame(self.df.aggregate(group_by, aggs))

    def sort(self, *exprs: Expr | SortExpr) -> DataFrame:
        """Sort the DataFrame by the specified sorting expressions.

        Note that any expression can be turned into a sort expression by
        calling its` ``sort`` method.

        Args:
            exprs: Sort expressions, applied in order.

        Returns:
            DataFrame after sorting.
        """
        exprs_raw = [sort_or_default(expr) for expr in exprs]
        return DataFrame(self.df.sort(*exprs_raw))

    def cast(self, mapping: dict[str, pa.DataType[Any]]) -> DataFrame:
        """Cast one or more columns to a different data type.

        Args:
            mapping: Mapped with column as key and column dtype as value.

        Returns:
            DataFrame after casting columns
        """
        exprs = [Expr.column(col).cast(dtype) for col, dtype in mapping.items()]
        return self.with_columns(exprs)

    def limit(self, count: int, offset: int = 0) -> DataFrame:
        """Return a new :py:class:`DataFrame` with a limited number of rows.

        Args:
            count: Number of rows to limit the DataFrame to.
            offset: Number of rows to skip.

        Returns:
            DataFrame after limiting.
        """
        return DataFrame(self.df.limit(count, offset))

    def head(self, n: int = 5) -> DataFrame:
        """Return a new :py:class:`DataFrame` with a limited number of rows.

        Args:
            n: Number of rows to take from the head of the DataFrame.

        Returns:
            DataFrame after limiting.
        """
        return DataFrame(self.df.limit(n, 0))

    def tail(self, n: int = 5) -> DataFrame:
        """Return a new :py:class:`DataFrame` with a limited number of rows.

        Be aware this could be potentially expensive since the row size needs to be
        determined of the dataframe. This is done by collecting it.

        Args:
            n: Number of rows to take from the tail of the DataFrame.

        Returns:
            DataFrame after limiting.
        """
        return DataFrame(self.df.limit(n, max(0, self.count() - n)))

    def collect(self) -> list[pa.RecordBatch]:
        """Execute this :py:class:`DataFrame` and collect results into memory.

        Prior to calling ``collect``, modifying a DataFrme simply updates a plan
        (no actual computation is performed). Calling ``collect`` triggers the
        computation.

        Returns:
            List of :py:class:`pyarrow.RecordBatch` collected from the DataFrame.
        """
        return self.df.collect()

    def cache(self) -> DataFrame:
        """Cache the DataFrame as a memory table.

        Returns:
            Cached DataFrame.
        """
        return DataFrame(self.df.cache())

    def collect_partitioned(self) -> list[list[pa.RecordBatch]]:
        """Execute this DataFrame and collect all partitioned results.

        This operation returns :py:class:`pyarrow.RecordBatch` maintaining the input
        partitioning.

        Returns:
            List of list of :py:class:`RecordBatch` collected from the
                DataFrame.
        """
        return self.df.collect_partitioned()

    def show(self, num: int = 20) -> None:
        """Execute the DataFrame and print the result to the console.

        Args:
            num: Number of lines to show.
        """
        self.df.show(num)

    def distinct(self) -> DataFrame:
        """Return a new :py:class:`DataFrame` with all duplicated rows removed.

        Returns:
            DataFrame after removing duplicates.
        """
        return DataFrame(self.df.distinct())

    @overload
    def join(
        self,
        right: DataFrame,
        on: str | Sequence[str],
        how: Literal["inner", "left", "right", "full", "semi", "anti"] = "inner",
        *,
        left_on: None = None,
        right_on: None = None,
        join_keys: None = None,
    ) -> DataFrame: ...

    @overload
    def join(
        self,
        right: DataFrame,
        on: None = None,
        how: Literal["inner", "left", "right", "full", "semi", "anti"] = "inner",
        *,
        left_on: str | Sequence[str],
        right_on: str | Sequence[str],
        join_keys: tuple[list[str], list[str]] | None = None,
    ) -> DataFrame: ...

    @overload
    def join(
        self,
        right: DataFrame,
        on: None = None,
        how: Literal["inner", "left", "right", "full", "semi", "anti"] = "inner",
        *,
        join_keys: tuple[list[str], list[str]],
        left_on: None = None,
        right_on: None = None,
    ) -> DataFrame: ...

    def join(
        self,
        right: DataFrame,
        on: str | Sequence[str] | tuple[list[str], list[str]] | None = None,
        how: Literal["inner", "left", "right", "full", "semi", "anti"] = "inner",
        *,
        left_on: str | Sequence[str] | None = None,
        right_on: str | Sequence[str] | None = None,
        join_keys: tuple[list[str], list[str]] | None = None,
    ) -> DataFrame:
        """Join this :py:class:`DataFrame` with another :py:class:`DataFrame`.

        `on` has to be provided or both `left_on` and `right_on` in conjunction.

        Args:
            right: Other DataFrame to join with.
            on: Column names to join on in both dataframes.
            how: Type of join to perform. Supported types are "inner", "left",
                "right", "full", "semi", "anti".
            left_on: Join column of the left dataframe.
            right_on: Join column of the right dataframe.
            join_keys: Tuple of two lists of column names to join on. [Deprecated]

        Returns:
            DataFrame after join.
        """
        # This check is to prevent breaking API changes where users prior to
        # DF 43.0.0 would  pass the join_keys as a positional argument instead
        # of a keyword argument.
        if isinstance(on, tuple) and len(on) == 2:
            if isinstance(on[0], list) and isinstance(on[1], list):
                join_keys = on  # type: ignore
                on = None

        if join_keys is not None:
            warnings.warn(
                "`join_keys` is deprecated, use `on` or `left_on` with `right_on`",
                category=DeprecationWarning,
                stacklevel=2,
            )
            left_on = join_keys[0]
            right_on = join_keys[1]

        if on is not None:
            if left_on is not None or right_on is not None:
                raise ValueError(
                    "`left_on` or `right_on` should not provided with `on`"
                )
            left_on = on
            right_on = on
        elif left_on is not None or right_on is not None:
            if left_on is None or right_on is None:
                raise ValueError("`left_on` and `right_on` should both be provided.")
        else:
            raise ValueError(
                "either `on` or `left_on` and `right_on` should be provided."
            )
        if isinstance(left_on, str):
            left_on = [left_on]
        if isinstance(right_on, str):
            right_on = [right_on]

        return DataFrame(self.df.join(right.df, how, left_on, right_on))

    def join_on(
        self,
        right: DataFrame,
        *on_exprs: Expr,
        how: Literal["inner", "left", "right", "full", "semi", "anti"] = "inner",
    ) -> DataFrame:
        """Join two :py:class:`DataFrame` using the specified expressions.

        On expressions are used to support in-equality predicates. Equality
        predicates are correctly optimized

        Args:
            right: Other DataFrame to join with.
            on_exprs: single or multiple (in)-equality predicates.
            how: Type of join to perform. Supported types are "inner", "left",
                "right", "full", "semi", "anti".

        Returns:
            DataFrame after join.
        """
        exprs = [expr.expr for expr in on_exprs]
        return DataFrame(self.df.join_on(right.df, exprs, how))

    def explain(self, verbose: bool = False, analyze: bool = False) -> DataFrame:
        """Return a DataFrame with the explanation of its plan so far.

        If ``analyze`` is specified, runs the plan and reports metrics.

        Args:
            verbose: If ``True``, more details will be included.
            analyze: If ``Tru`e``, the plan will run and metrics reported.

        Returns:
            DataFrame with the explanation of its plan.
        """
        return DataFrame(self.df.explain(verbose, analyze))

    def logical_plan(self) -> LogicalPlan:
        """Return the unoptimized ``LogicalPlan``.

        Returns:
            Unoptimized logical plan.
        """
        return LogicalPlan(self.df.logical_plan())

    def optimized_logical_plan(self) -> LogicalPlan:
        """Return the optimized ``LogicalPlan``.

        Returns:
            Optimized logical plan.
        """
        return LogicalPlan(self.df.optimized_logical_plan())

    def execution_plan(self) -> ExecutionPlan:
        """Return the execution/physical plan.

        Returns:
            Execution plan.
        """
        return ExecutionPlan(self.df.execution_plan())

    def repartition(self, num: int) -> DataFrame:
        """Repartition a DataFrame into ``num`` partitions.

        The batches allocation uses a round-robin algorithm.

        Args:
            num: Number of partitions to repartition the DataFrame into.

        Returns:
            Repartitioned DataFrame.
        """
        return DataFrame(self.df.repartition(num))

    def repartition_by_hash(self, *exprs: Expr, num: int) -> DataFrame:
        """Repartition a DataFrame using a hash partitioning scheme.

        Args:
            exprs: Expressions to evaluate and perform hashing on.
            num: Number of partitions to repartition the DataFrame into.

        Returns:
            Repartitioned DataFrame.
        """
        exprs = [expr.expr for expr in exprs]
        return DataFrame(self.df.repartition_by_hash(*exprs, num=num))

    def union(self, other: DataFrame, distinct: bool = False) -> DataFrame:
        """Calculate the union of two :py:class:`DataFrame`.

        The two :py:class:`DataFrame` must have exactly the same schema.

        Args:
            other: DataFrame to union with.
            distinct: If ``True``, duplicate rows will be removed.

        Returns:
            DataFrame after union.
        """
        return DataFrame(self.df.union(other.df, distinct))

    def union_distinct(self, other: DataFrame) -> DataFrame:
        """Calculate the distinct union of two :py:class:`DataFrame`.

        The two :py:class:`DataFrame` must have exactly the same schema.
        Any duplicate rows are discarded.

        Args:
            other: DataFrame to union with.

        Returns:
            DataFrame after union.
        """
        return DataFrame(self.df.union_distinct(other.df))

    def intersect(self, other: DataFrame) -> DataFrame:
        """Calculate the intersection of two :py:class:`DataFrame`.

        The two :py:class:`DataFrame` must have exactly the same schema.

        Args:
            other:  DataFrame to intersect with.

        Returns:
            DataFrame after intersection.
        """
        return DataFrame(self.df.intersect(other.df))

    def except_all(self, other: DataFrame) -> DataFrame:
        """Calculate the exception of two :py:class:`DataFrame`.

        The two :py:class:`DataFrame` must have exactly the same schema.

        Args:
            other: DataFrame to calculate exception with.

        Returns:
            DataFrame after exception.
        """
        return DataFrame(self.df.except_all(other.df))

    def write_csv(self, path: str | pathlib.Path, with_header: bool = False) -> None:
        """Execute the :py:class:`DataFrame`  and write the results to a CSV file.

        Args:
            path: Path of the CSV file to write.
            with_header: If true, output the CSV header row.
        """
        self.df.write_csv(str(path), with_header)

    def write_parquet(
        self,
        path: str | pathlib.Path,
        compression: Union[str, Compression] = Compression.ZSTD,
        compression_level: int | None = None,
    ) -> None:
        """Execute the :py:class:`DataFrame` and write the results to a Parquet file.

        Args:
            path: Path of the Parquet file to write.
            compression: Compression type to use. Default is "ZSTD".
                Available compression types are:
                - "uncompressed": No compression.
                - "snappy": Snappy compression.
                - "gzip": Gzip compression.
                - "brotli": Brotli compression.
                - "lz4": LZ4 compression.
                - "lz4_raw": LZ4_RAW compression.
                - "zstd": Zstandard compression.
            Note: LZO is not yet implemented in arrow-rs and is therefore excluded.
            compression_level: Compression level to use. For ZSTD, the
                recommended range is 1 to 22, with the default being 4. Higher levels
                provide better compression but slower speed.
        """
        # Convert string to Compression enum if necessary
        if isinstance(compression, str):
            compression = Compression.from_str(compression)

        if compression in {Compression.GZIP, Compression.BROTLI, Compression.ZSTD}:
            if compression_level is None:
                compression_level = compression.get_default_level()

        self.df.write_parquet(str(path), compression.value, compression_level)

    def write_json(self, path: str | pathlib.Path) -> None:
        """Execute the :py:class:`DataFrame` and write the results to a JSON file.

        Args:
            path: Path of the JSON file to write.
        """
        self.df.write_json(str(path))

    def to_arrow_table(self) -> pa.Table:
        """Execute the :py:class:`DataFrame` and convert it into an Arrow Table.

        Returns:
            Arrow Table.
        """
        return self.df.to_arrow_table()

    def execute_stream(self) -> RecordBatchStream:
        """Executes this DataFrame and returns a stream over a single partition.

        Returns:
            Record Batch Stream over a single partition.
        """
        return RecordBatchStream(self.df.execute_stream())

    def execute_stream_partitioned(self) -> list[RecordBatchStream]:
        """Executes this DataFrame and returns a stream for each partition.

        Returns:
            One record batch stream per partition.
        """
        streams = self.df.execute_stream_partitioned()
        return [RecordBatchStream(rbs) for rbs in streams]

    def to_pandas(self) -> pd.DataFrame:
        """Execute the :py:class:`DataFrame` and convert it into a Pandas DataFrame.

        Returns:
            Pandas DataFrame.
        """
        return self.df.to_pandas()

    def to_pylist(self) -> list[dict[str, Any]]:
        """Execute the :py:class:`DataFrame` and convert it into a list of dictionaries.

        Returns:
            List of dictionaries.
        """
        return self.df.to_pylist()

    def to_pydict(self) -> dict[str, list[Any]]:
        """Execute the :py:class:`DataFrame` and convert it into a dictionary of lists.

        Returns:
            Dictionary of lists.
        """
        return self.df.to_pydict()

    def to_polars(self) -> pl.DataFrame:
        """Execute the :py:class:`DataFrame` and convert it into a Polars DataFrame.

        Returns:
            Polars DataFrame.
        """
        return self.df.to_polars()

    def count(self) -> int:
        """Return the total number of rows in this :py:class:`DataFrame`.

        Note that this method will actually run a plan to calculate the
        count, which may be slow for large or complicated DataFrames.

        Returns:
            Number of rows in the DataFrame.
        """
        return self.df.count()

    @deprecated("Use :py:func:`unnest_columns` instead.")
    def unnest_column(self, column: str, preserve_nulls: bool = True) -> DataFrame:
        """See :py:func:`unnest_columns`."""
        return DataFrame(self.df.unnest_column(column, preserve_nulls=preserve_nulls))

    def unnest_columns(self, *columns: str, preserve_nulls: bool = True) -> DataFrame:
        """Expand columns of arrays into a single row per array element.

        Args:
            columns: Column names to perform unnest operation on.
            preserve_nulls: If False, rows with null entries will not be
                returned.

        Returns:
            A DataFrame with the columns expanded.
        """
        columns = [c for c in columns]
        return DataFrame(self.df.unnest_columns(columns, preserve_nulls=preserve_nulls))

    def __arrow_c_stream__(self, requested_schema: pa.Schema) -> Any:
        """Export an Arrow PyCapsule Stream.

        This will execute and collect the DataFrame. We will attempt to respect the
        requested schema, but only trivial transformations will be applied such as only
        returning the fields listed in the requested schema if their data types match
        those in the DataFrame.

        Args:
            requested_schema: Attempt to provide the DataFrame using this schema.

        Returns:
            Arrow PyCapsule object.
        """
        return self.df.__arrow_c_stream__(requested_schema)

    def transform(self, func: Callable[..., DataFrame], *args: Any) -> DataFrame:
        """Apply a function to the current DataFrame which returns another DataFrame.

        This is useful for chaining together multiple functions. For example::

            def add_3(df: DataFrame) -> DataFrame:
                return df.with_column("modified", lit(3))

            def within_limit(df: DataFrame, limit: int) -> DataFrame:
                return df.filter(col("a") < lit(limit)).distinct()

            df = df.transform(modify_df).transform(within_limit, 4)

        Args:
            func: A callable function that takes a DataFrame as it's first argument
            args: Zero or more arguments to pass to `func`

        Returns:
            DataFrame: After applying func to the original dataframe.
        """
        return func(self, *args)