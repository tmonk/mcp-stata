* test_assert_matrix_fail.do
matrix A = (1, 2 \ 3, 4)
matrix B = (1, 2 \ 3, 5)
st_assert_matrix A, expected(B)
